from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from nextloop import (
    AgentLoop,
    Completed,
    CompositeToolRuntime,
    Event,
    EventStore,
    EventType,
    FinalMessage,
    Message,
    ModelProvider,
    ToolContext,
    ToolEffect,
    ToolExecutionMode,
    ToolRegistry,
    ToolRuntime,
    ToolSpec,
    TurnContext,
    TurnStatus,
    skill_view,
)
from nextloop.events.codec import message_from_data
from nextloop.execute.result_read import with_result_reads

from .contracts import (
    IngressEnvelope,
    ReplyKind,
    ReplyTarget,
    ReportStatus,
    SessionIdentity,
    SpecialistId,
    TaskKind,
    TaskStatus,
    verify_nextloop_version,
)
from .db import ChildTaskSpec, IngressAction, NikaLedger, TaskRecord
from .feishu import (
    FeishuTransport,
    LiveStatusCardSession,
    PreviewProgressBridge,
)
from .orchestration import (
    CONSULT_FORBIDDEN_TOOLS,
    register_specialist_orchestration,
)
from .packs import SpecialistPack
from .pocket import PocketCallbackNotice
from .tools import NikaToolRuntime

ORCHESTRATION_TOOLS = ("dispatch_task", "report_task", "consult_peer")


@dataclass
class SchedulerDeps:
    ledger: NikaLedger
    store: EventStore
    provider: ModelProvider
    runtime: NikaToolRuntime
    packs: Mapping[SpecialistId, SpecialistPack]
    feishu_transport: FeishuTransport
    shared_skills_dir: Path | None = None
    pocket_callback_sender: Callable[[PocketCallbackNotice], Any] | None = None
    clock: Callable[[], float] = time.monotonic


@dataclass(frozen=True)
class RecoverySummary:
    redelivered: int
    failed_interrupted: int
    resumed_queued: int


def _append_missing_receipts(text: str, receipts: Sequence[str]) -> str:
    missing = [rec for rec in receipts if rec not in text]
    if not missing:
        return text
    return "\n\n".join([text.rstrip(), *missing])


class TaskDeliveryOwner:
    def __init__(
        self,
        task: TaskRecord,
        deps: SchedulerDeps,
        bridge: PreviewProgressBridge | None = None,
    ) -> None:
        self._task = task
        self._deps = deps
        self._bridge = bridge

    async def deliver(self, message: FinalMessage) -> None:
        if self._bridge is not None:
            await self._bridge.flush()
        latest = await self._deps.ledger.get_task(self._task.task_id)
        if latest is None:
            raise LookupError(f"Task missing on delivery: {self._task.task_id}")
        receipts = self._deps.runtime.pop_wiki_receipts(latest.session_id)
        text = _append_missing_receipts(
            latest.summary or message.content, receipts
        )
        suppress_external = latest.kind == TaskKind.CONSULT or (
            latest.report_status
            in (ReportStatus.HANDOFF, ReportStatus.DISPATCHED)
        )
        if not suppress_external:
            await self._send_external(latest, text)
        await self._deps.ledger.settle_delivered(
            latest.task_id, message.final_message_id, text
        )

    async def _send_external(self, task: TaskRecord, text: str) -> None:
        target = task.reply_target
        if target is None:
            return
        if target.kind == ReplyKind.FEISHU_CARD:
            if self._bridge is not None:
                await self._bridge.card.finalize(text)
            else:
                await self._deps.feishu_transport.send_card(
                    target.channel_id, text
                )
        elif target.kind == ReplyKind.FEISHU_COMMENT:
            cid = str(target.metadata.get("comment_id", ""))
            await self._deps.feishu_transport.reply_comment(
                target.channel_id, cid, text
            )
        elif (
            target.kind == ReplyKind.POCKET_CALLBACK
            and self._deps.pocket_callback_sender is not None
        ):
            locked = self._deps.runtime.pop_cloud_locked(task.session_id)
            reason = (
                "cloud_locked"
                if locked
                else (
                    task.report_status.value
                    if task.report_status
                    in (ReportStatus.NEED_DECISION, ReportStatus.BLOCKED)
                    else ""
                )
            )
            await self._deps.pocket_callback_sender(
                PocketCallbackNotice(target, text, reason)
            )


DISPATCH_TOOL_SPEC = ToolSpec(
    name="dispatch_task",
    description=(
        "Dispatch a heavy multi-step task to a specialist "
        "('coder', 'doc_research', 'eval', 'top_talent') with "
        "complete goal and constraints."
    ),
    parameters={
        "type": "object",
        "properties": {
            "specialist": {
                "type": "string",
                "enum": ["coder", "doc_research", "eval", "top_talent"],
            },
            "goal": {"type": "string"},
        },
        "required": ["specialist", "goal"],
        "additionalProperties": False,
    },
    mode=ToolExecutionMode.EXCLUSIVE,
    effect=ToolEffect.NON_IDEMPOTENT,
)


def _validate_dispatch_args(
    args: Mapping[str, Any], packs: Mapping[SpecialistId, SpecialistPack]
) -> tuple[SpecialistId | None, str, str | None]:
    raw_spec = args.get("specialist")
    raw_goal = args.get("goal")
    if not isinstance(raw_spec, str) or not isinstance(raw_goal, str):
        return None, "", "specialist and goal must be strings"
    goal = raw_goal.strip()
    if not goal:
        return None, "", "goal must be non-empty"
    try:
        spec_id = SpecialistId(raw_spec)
    except ValueError:
        return None, "", f"Unknown specialist: {raw_spec}"
    if spec_id == SpecialistId.MAIN:
        return None, "", "Cannot dispatch to 'main'"
    if spec_id not in packs and len(packs) > 1:
        return None, "", f"Specialist '{spec_id.value}' is not configured"
    return spec_id, goal, None


class NikaScheduler:
    def __init__(self, deps: SchedulerDeps) -> None:
        verify_nextloop_version()
        self._deps = deps
        self._loop = AgentLoop()
        self._bg_tasks: set[asyncio.Task[None]] = set()
        self._runners: dict[str, asyncio.Task[None]] = {}
        self._bridges: dict[str, PreviewProgressBridge] = {}
        self._pending_steers: dict[str, list[tuple[str, str]]] = {}
        self._register_orchestration_tools()

    def set_provider(self, provider: ModelProvider) -> None:
        self._deps.provider = provider

    def _register_orchestration_tools(self) -> None:
        existing = {spec.name for spec in self._deps.runtime.catalog()}
        if "dispatch_task" not in existing:
            self._deps.runtime.register(
                DISPATCH_TOOL_SPEC, self._handle_dispatch_tool
            )
        register_specialist_orchestration(
            self._deps.runtime,
            self._deps.ledger,
            self._deps.packs,
            self._run_consult_child,
        )

    async def _run_consult_child(self, child: TaskRecord) -> str | None:
        try:
            await self._run_task(child, None, child.task_id)
        except asyncio.CancelledError:
            await self._deps.ledger.cancel_task_if_open(child.task_id)
            raise
        settled = await self._deps.ledger.get_task(child.task_id)
        if (
            settled is None
            or settled.status != TaskStatus.DONE
            or not settled.summary
        ):
            return None
        return settled.summary

    async def _spawn_handoff_to_main(self, settled: TaskRecord) -> None:
        if (
            settled.kind == TaskKind.CONSULT
            or settled.report_status != ReportStatus.HANDOFF
            or settled.specialist == SpecialistId.MAIN
        ):
            return
        rerouted = await self._deps.ledger.get_handoff_child(settled.task_id)
        if rerouted is not None and rerouted.status == TaskStatus.QUEUED:
            self._spawn_runner(rerouted, None, rerouted.task_id)

    async def _resolve_dispatch_target(
        self, parent: TaskRecord, spec_id: SpecialistId, goal: str
    ) -> tuple[str, ReplyTarget | None]:
        thread_key = parent.thread_key
        reply_target = parent.reply_target
        if (
            thread_key.startswith("feishu:dm:")
            and reply_target is not None
            and reply_target.kind == ReplyKind.FEISHU_CARD
        ):
            banner = f"📋 Dispatched to `{spec_id.value}`: {goal[:120]}"
            parent_bridge = self._bridges.get(parent.session_id)
            if parent_bridge is not None:
                card_id = await parent_bridge.card.finalize(banner)
            else:
                card_id = await self._deps.feishu_transport.send_card(
                    reply_target.channel_id, banner
                )
            return (
                f"feishu:thread:{card_id}",
                ReplyTarget(kind=ReplyKind.FEISHU_CARD, channel_id=card_id),
            )
        return thread_key, reply_target

    async def _handle_dispatch_tool(
        self, args: Mapping[str, Any], ctx: ToolContext
    ) -> Completed:
        identity = self._deps.runtime.get_identity(ctx.session_id)
        if identity is None or identity.specialist != SpecialistId.MAIN:
            return Completed(
                "Only 'main' may call dispatch_task", is_error=True
            )
        spec_id, goal, err = _validate_dispatch_args(args, self._deps.packs)
        if err is not None or spec_id is None:
            return Completed(err or "invalid dispatch", is_error=True)
        parent = await self._deps.ledger.get_task(identity.task_id)
        if parent is None:
            return Completed("Parent task not found", is_error=True)
        await self._deps.ledger.record_report(
            parent.task_id,
            ReportStatus.DISPATCHED,
            f"Dispatched to {spec_id.value}",
        )
        thread_key, reply_target = await self._resolve_dispatch_target(
            parent, spec_id, goal
        )
        child = await self._deps.ledger.create_child_task(
            ChildTaskSpec(
                parent_task_id=parent.task_id,
                origin_event_id=parent.origin_event_id,
                origin_call_id=f"call_{ctx.turn}_{ctx.step}",
                thread_key=thread_key,
                kind=TaskKind.DISPATCH,
                specialist=spec_id,
                depth=0,
                prompt=goal,
                reply_target=reply_target,
            )
        )
        if spec_id in self._deps.packs:
            self._spawn_runner(child, None, None)
        return Completed(
            f"Dispatched task {child.task_id} to {spec_id.value} on {thread_key}",
            concludes_turn=True,
        )

    async def ingest(self, envelope: IngressEnvelope) -> str:
        decision = await self._deps.ledger.accept_ingress(envelope)
        if decision.action == IngressAction.DUPLICATE:
            return decision.task.task_id if decision.task else "duplicate"
        assert decision.task is not None
        task = decision.task
        if decision.action == IngressAction.STEER_ACTIVE:
            steered = await self._loop.steer(
                task.session_id, envelope.prompt, input_id=envelope.event_id
            )
            if not steered:
                self._pending_steers.setdefault(task.task_id, []).append(
                    (envelope.event_id, envelope.prompt)
                )
            return task.task_id
        if decision.action == IngressAction.RESUME_DECISION:
            self._spawn_runner(task, envelope.prompt, envelope.event_id)
            return task.task_id
        if decision.action == IngressAction.HOLD_BLOCKED:
            return task.task_id
        self._spawn_runner(task, None, envelope.event_id)
        return task.task_id

    def _spawn_runner(
        self,
        task: TaskRecord,
        resume_input: str | None,
        input_id: str | None,
    ) -> None:
        bg = asyncio.create_task(self._run_task(task, resume_input, input_id))
        self._bg_tasks.add(bg)
        self._runners[task.task_id] = bg

        def _cleanup(done_task: asyncio.Task[None]) -> None:
            self._bg_tasks.discard(done_task)
            if self._runners.get(task.task_id) is done_task:
                self._runners.pop(task.task_id, None)

        bg.add_done_callback(_cleanup)

    @staticmethod
    def _event_to_prior_message(ev: Event) -> Message | None:
        if ev.event_type not in (
            EventType.USER_MESSAGE,
            EventType.ASSISTANT_MESSAGE,
        ):
            return None
        msg = message_from_data(ev.payload["message"])
        if not msg.content or msg.content.startswith("[WorkingContext"):
            return None
        return Message(role=msg.role, content=msg.content)

    async def _hydrate_prior_messages(
        self, thread_key: str, current_session_id: str
    ) -> tuple[Message, ...]:
        prev_sid = await self._deps.ledger.get_thread_last_session(thread_key)
        if not prev_sid or prev_sid == current_session_id:
            return ()
        events = await self._deps.store.load_surface(prev_sid)
        hydrated = [
            m
            for m in (self._event_to_prior_message(ev) for ev in events)
            if m is not None
        ]
        return tuple(hydrated[-6:])

    @staticmethod
    def _allowed_tools_for(
        task: TaskRecord, pack: SpecialistPack
    ) -> frozenset[str]:
        if task.kind != TaskKind.CONSULT:
            return pack.tools
        return frozenset(
            t for t in pack.tools if t not in CONSULT_FORBIDDEN_TOOLS
        )

    def _assemble_runtime_and_config(
        self,
        task: TaskRecord,
        pack: SpecialistPack,
        prior_msgs: tuple[Message, ...],
    ) -> tuple[ToolRuntime, Any]:
        identity = SessionIdentity(
            session_id=task.session_id,
            task_id=task.task_id,
            specialist=task.specialist,
            kind=task.kind,
            depth=task.depth,
        )
        scoped: ToolRuntime = self._deps.runtime.scope(
            identity, self._allowed_tools_for(task, pack)
        )
        loop_cfg = replace(pack.loop_config, bootstrap_messages=prior_msgs)
        if pack.skill_registry is not None:
            skill_reg = ToolRegistry()
            skill_reg.register(
                ToolSpec(
                    "skill_view",
                    "Load instructions for an available Skill",
                    {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                        "required": ["name"],
                        "additionalProperties": False,
                    },
                    mode=ToolExecutionMode.PARALLEL,
                    effect=ToolEffect.READ_ONLY,
                ),
                skill_view(pack.skill_registry),
            )
            scoped = CompositeToolRuntime([scoped, skill_reg])
            meta = "\n".join(
                f"- {s.name}: {s.description}"
                for s in pack.skill_registry.list()
            )
            loop_cfg = replace(
                loop_cfg,
                system_prompt=f"{loop_cfg.system_prompt}\n\nAvailable Skills:\n{meta}",
            )
        wrapped = with_result_reads(
            scoped, self._deps.store, loop_cfg.tool_result_bytes
        )
        return wrapped, loop_cfg

    def _drain_initial_prompt(
        self, task: TaskRecord, resume_input: str | None
    ) -> str:
        base = resume_input if resume_input is not None else task.prompt
        queued = self._pending_steers.pop(task.task_id, [])
        if not queued:
            return base
        return "\n\n".join([base, *(text for _, text in queued)])

    async def _start_task_bridge(
        self, task: TaskRecord
    ) -> PreviewProgressBridge | None:
        bridge = self._make_progress_bridge(task)
        if bridge is not None:
            self._bridges[task.session_id] = bridge
            await bridge.card.emit_progress(
                f"⏳ `{task.specialist.value}` thinking..."
            )
        return bridge

    async def _run_task(
        self,
        task: TaskRecord,
        resume_input: str | None,
        input_id: str | None,
    ) -> None:
        current = await self._deps.ledger.get_task(task.task_id)
        if current is None or current.status == TaskStatus.FAILED:
            return
        pack = self._deps.packs.get(task.specialist)
        if pack is None:
            await self._deps.ledger.set_task_status(
                task.task_id, TaskStatus.FAILED
            )
            return
        await self._deps.ledger.set_task_status(
            task.task_id, TaskStatus.RUNNING
        )
        bridge = await self._start_task_bridge(task)
        prior = (
            ()
            if task.kind == TaskKind.CONSULT
            else await self._hydrate_prior_messages(
                task.thread_key, task.session_id
            )
        )
        tools, loop_cfg = self._assemble_runtime_and_config(task, pack, prior)
        ctx = TurnContext(
            session_id=task.session_id,
            initial_input=self._drain_initial_prompt(task, resume_input),
            config=loop_cfg,
            store=self._deps.store,
            provider=self._deps.provider,
            tools=tools,
            delivery=TaskDeliveryOwner(task, self._deps, bridge),
            input_id=input_id or task.origin_event_id or task.task_id,
            preview=bridge,
        )
        outcome = await self._execute_turn_safely(task.task_id, ctx, bridge)
        await self._finalize_non_delivered_outcome(task.task_id, outcome.status)
        latest = await self._deps.ledger.get_task(task.task_id)
        if latest is not None:
            await self._spawn_handoff_to_main(latest)

    async def _execute_turn_safely(
        self,
        task_id: str,
        ctx: TurnContext,
        bridge: PreviewProgressBridge | None,
    ) -> Any:
        try:
            return await self._loop.run(ctx)
        # bits:allow(BCS013): mark FAILED before re-raising
        except Exception:
            await self._deps.ledger.set_task_status(task_id, TaskStatus.FAILED)
            raise
        finally:
            self._bridges.pop(ctx.session_id, None)
            self._pending_steers.pop(task_id, None)
            if bridge is not None:
                await bridge.flush()
            self._deps.runtime.cleanup_session(ctx.session_id)

    def _make_progress_bridge(
        self, task: TaskRecord
    ) -> PreviewProgressBridge | None:
        target = task.reply_target
        if target is None or target.kind != ReplyKind.FEISHU_CARD:
            return None
        card = LiveStatusCardSession(
            transport=self._deps.feishu_transport,
            channel_id=target.channel_id,
            clock=self._deps.clock,
        )
        return PreviewProgressBridge(card)

    async def _finalize_non_delivered_outcome(
        self, task_id: str, status: TurnStatus
    ) -> None:
        latest = await self._deps.ledger.get_task(task_id)
        if latest is None or latest.status != TaskStatus.RUNNING:
            return
        if status == TurnStatus.APPROVAL_PENDING:
            await self._deps.ledger.set_task_status(
                task_id, TaskStatus.NEED_DECISION
            )
        elif status in (TurnStatus.BLOCKED, TurnStatus.DELIVERY_UNKNOWN):
            await self._deps.ledger.set_task_status(task_id, TaskStatus.BLOCKED)
        elif status in (TurnStatus.CANCELLED, TurnStatus.FAILED):
            await self._deps.ledger.set_task_status(task_id, TaskStatus.FAILED)

    async def _recover_running_task(self, task: TaskRecord) -> tuple[int, int]:
        try:
            outcome = await self._loop.recover(
                task.session_id,
                self._deps.store,
                TaskDeliveryOwner(task, self._deps, None),
                force=True,
            )
        # bits:allow(BCS013): isolate corrupted session during boot recovery
        except Exception:
            await self._deps.ledger.set_task_status(
                task.task_id, TaskStatus.FAILED
            )
            return 0, 1
        if outcome.delivered_final_ids:
            return 1, 0
        if outcome.delivery_unknown_final_ids:
            await self._deps.ledger.set_task_status(
                task.task_id, TaskStatus.BLOCKED
            )
            return 0, 0
        await self._deps.ledger.set_task_status(task.task_id, TaskStatus.FAILED)
        return 0, 1

    async def _resume_or_fail_queued(self, task: TaskRecord) -> int:
        if (
            task.kind == TaskKind.CONSULT
            or task.specialist not in self._deps.packs
        ):
            await self._deps.ledger.set_task_status(
                task.task_id, TaskStatus.FAILED
            )
            return 0
        self._spawn_runner(task, None, task.origin_event_id or task.task_id)
        return 1

    async def _fail_if_orphan_consult(self, task: TaskRecord) -> int:
        if task.kind != TaskKind.CONSULT:
            return 0
        await self._deps.ledger.set_task_status(task.task_id, TaskStatus.FAILED)
        return 1

    async def recover(self) -> RecoverySummary:
        initial = await self._deps.ledger.list_unfinished_tasks()
        running = [t for t in initial if t.status == TaskStatus.RUNNING]
        run_counts = [await self._recover_running_task(t) for t in running]
        redelivered = sum(r for r, _ in run_counts)
        failed_int = sum(f for _, f in run_counts)
        remaining = await self._deps.ledger.list_unfinished_tasks()
        queued = [t for t in remaining if t.status == TaskStatus.QUEUED]
        resumed = sum([await self._resume_or_fail_queued(t) for t in queued])
        return RecoverySummary(
            redelivered=redelivered,
            failed_interrupted=failed_int,
            resumed_queued=resumed,
        )

    async def recover_offline(self) -> RecoverySummary:
        initial = await self._deps.ledger.list_unfinished_tasks()
        running = [t for t in initial if t.status == TaskStatus.RUNNING]
        run_counts = [await self._recover_running_task(t) for t in running]
        redelivered = sum(r for r, _ in run_counts)
        failed_int = sum(f for _, f in run_counts)
        remaining = await self._deps.ledger.list_unfinished_tasks()
        queued = [t for t in remaining if t.status == TaskStatus.QUEUED]
        orphan_c = sum([await self._fail_if_orphan_consult(t) for t in queued])
        return RecoverySummary(
            redelivered=redelivered,
            failed_interrupted=failed_int + orphan_c,
            resumed_queued=0,
        )

    async def stop(self, thread_key: str) -> bool:
        active = await self._deps.ledger.get_active_task(thread_key)
        if active is None:
            return False
        children = await self._deps.ledger.list_open_children(active.task_id)
        for ch in children:
            await self._loop.cancel(ch.session_id, "user_stop")
        cancelled = await self._loop.cancel(active.session_id, "user_stop")
        if not cancelled:
            runner = self._runners.get(active.task_id)
            if runner is not None and not runner.done():
                runner.cancel()
        await self._deps.ledger.cancel_task_if_open(active.task_id)
        return True

    async def drain(self) -> None:
        while self._bg_tasks:
            pending = tuple(self._bg_tasks)
            await asyncio.gather(*pending, return_exceptions=True)

    async def close(self) -> None:
        for bg in tuple(self._bg_tasks):
            bg.cancel()
        if self._bg_tasks:
            await asyncio.gather(*self._bg_tasks, return_exceptions=True)
