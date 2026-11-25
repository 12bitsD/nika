from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from nextloop import (
    Completed,
    ToolContext,
    ToolEffect,
    ToolExecutionMode,
    ToolSpec,
)

from .contracts import (
    ReportStatus,
    SessionIdentity,
    SpecialistId,
    TaskKind,
    TaskStatus,
)
from .db import ChildTaskSpec, NikaLedger, TaskRecord
from .packs import SpecialistPack
from .tools import NikaToolRuntime, req_str

_AsyncHandler = Callable[[Mapping[str, Any], ToolContext], Awaitable[Completed]]

REPORT_STATUSES = (
    ReportStatus.DONE,
    ReportStatus.NEED_DECISION,
    ReportStatus.BLOCKED,
    ReportStatus.HANDOFF,
)
REPORT_STATUS_VALUES = tuple(s.value for s in REPORT_STATUSES)
CONSULT_ALLOWED_CALLERS = (
    SpecialistId.MAIN,
    SpecialistId.CODER,
    SpecialistId.DOC_RESEARCH,
)
CONSULT_TARGETS = (
    SpecialistId.TOP_TALENT,
    SpecialistId.CODER,
    SpecialistId.DOC_RESEARCH,
    SpecialistId.EVAL,
)
CONSULT_FORBIDDEN_TOOLS = (
    "write",
    "edit",
    "bash",
    "pocket",
    "session_ctl",
    "dispatch_task",
)

REPORT_TASK_SPEC = ToolSpec(
    name="report_task",
    description=(
        "Conclude a specialist task with status ('done', 'need_decision', "
        "'blocked', 'handoff') and concise summary."
    ),
    parameters={
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": list(REPORT_STATUS_VALUES)},
            "summary": {"type": "string"},
        },
        "required": ["status", "summary"],
        "additionalProperties": False,
    },
    mode=ToolExecutionMode.EXCLUSIVE,
    effect=ToolEffect.NON_IDEMPOTENT,
)

CONSULT_PEER_SPEC = ToolSpec(
    name="consult_peer",
    description=(
        "Request a clean-context blind review from a peer specialist "
        "passing ONLY the artifact and specific question (depth=1 hard cap)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "specialist": {
                "type": "string",
                "enum": [t.value for t in CONSULT_TARGETS],
            },
            "artifact": {"type": "string"},
            "question": {"type": "string"},
        },
        "required": ["specialist", "artifact", "question"],
        "additionalProperties": False,
    },
    mode=ToolExecutionMode.PARALLEL,
    effect=ToolEffect.IDEMPOTENT,
)


def _validate_report_call(
    ident: SessionIdentity | None, args: Mapping[str, Any]
) -> tuple[ReportStatus | None, str, str | None]:
    if ident is None or ident.specialist == SpecialistId.MAIN:
        return None, "", "Only specialists may call report_task"
    raw_status = req_str(args, "status")
    summary = (req_str(args, "summary") or "").strip()
    if raw_status not in REPORT_STATUS_VALUES or not summary:
        return None, "", "Valid status and summary required"
    rep = ReportStatus(raw_status)
    if ident.kind == TaskKind.CONSULT and rep != ReportStatus.DONE:
        return None, "", "consult_peer may only report status='done'"
    return rep, summary, None


def _check_consult_caller(ident: SessionIdentity | None) -> str | None:
    if ident is None:
        return "Unbound session identity"
    if ident.depth >= 1 or ident.kind == TaskKind.CONSULT:
        return "Nested consult_peer is forbidden at depth >= 1"
    if ident.specialist not in CONSULT_ALLOWED_CALLERS:
        return f"{ident.specialist.value} may not call consult_peer"
    return None


def _validate_consult_args(
    ident: SessionIdentity,
    args: Mapping[str, Any],
    packs: Mapping[SpecialistId, SpecialistPack],
) -> tuple[SpecialistId | None, str, str | None]:
    raw_spec = req_str(args, "specialist")
    artifact = (req_str(args, "artifact") or "").strip()
    question = (req_str(args, "question") or "").strip()
    if raw_spec is None or not artifact or not question:
        return None, "", "specialist, artifact, and question must be non-empty"
    try:
        target_spec = SpecialistId(raw_spec)
    except ValueError:
        return None, "", f"Unknown peer specialist: {raw_spec}"
    if target_spec not in CONSULT_TARGETS or target_spec not in packs:
        return None, "", f"Peer specialist '{target_spec.value}' unavailable"
    if target_spec == ident.specialist:
        return None, "", f"{ident.specialist.value} may not consult_peer itself"
    prompt = (
        f"[Peer Review Question]\n{question}\n\n"
        f"[Artifact Under Review]\n{artifact}"
    )
    return target_spec, prompt, None


async def _reject_excess_handoff(
    ledger: NikaLedger, task: TaskRecord, rep: ReportStatus
) -> str | None:
    if rep != ReportStatus.HANDOFF:
        return None
    ev_key = task.origin_event_id or task.task_id
    if await ledger.count_handoffs(ev_key) >= 1:
        return "Handoff limit (1) reached; report blocked instead"
    return None


def _make_report_handler(
    runtime: NikaToolRuntime, ledger: NikaLedger
) -> _AsyncHandler:
    async def _handle_report(
        args: Mapping[str, Any], ctx: ToolContext
    ) -> Completed:
        ident = runtime.get_identity(ctx.session_id)
        rep, summary, err = _validate_report_call(ident, args)
        if err is not None or rep is None or ident is None:
            return Completed(err or "Invalid report", is_error=True)
        task = await ledger.get_task(ident.task_id)
        if task is None:
            return Completed("Task not found", is_error=True)
        ho_err = await _reject_excess_handoff(ledger, task, rep)
        if ho_err is not None:
            return Completed(ho_err, is_error=True)
        await ledger.record_report(task.task_id, rep, summary)
        return Completed(summary, concludes_turn=True)

    return _handle_report


def _build_consult_child_spec(
    parent: TaskRecord,
    ctx: ToolContext,
    target_spec: SpecialistId,
    prompt: str,
) -> ChildTaskSpec:
    call_key = ctx.operation_id or f"consult_{ctx.turn}_{ctx.step}"
    return ChildTaskSpec(
        parent_task_id=parent.task_id,
        origin_event_id=parent.origin_event_id or parent.task_id,
        origin_call_id=call_key,
        thread_key=parent.thread_key,
        kind=TaskKind.CONSULT,
        specialist=target_spec,
        depth=1,
        prompt=prompt,
        reply_target=None,
    )


async def _execute_or_replay_consult(
    ledger: NikaLedger,
    child: TaskRecord,
    run_consult: Callable[[TaskRecord], Awaitable[str | None]],
) -> Completed:
    if child.status == TaskStatus.DONE:
        return Completed(child.summary or "(empty review)")
    if child.status == TaskStatus.RUNNING:
        return Completed(
            "Concurrent duplicate consult_peer rejected", is_error=True
        )
    if child.status == TaskStatus.FAILED:
        await ledger.set_task_status(child.task_id, TaskStatus.QUEUED)
    out = await run_consult(child)
    if not out:
        return Completed(
            "(consult_peer failed or produced no output)", is_error=True
        )
    return Completed(out)


def _make_consult_handler(
    runtime: NikaToolRuntime,
    ledger: NikaLedger,
    packs: Mapping[SpecialistId, SpecialistPack],
    run_consult: Callable[[TaskRecord], Awaitable[str | None]],
) -> _AsyncHandler:
    async def _handle_consult(
        args: Mapping[str, Any], ctx: ToolContext
    ) -> Completed:
        ident = runtime.get_identity(ctx.session_id)
        caller_err = _check_consult_caller(ident)
        if caller_err is not None or ident is None:
            return Completed(caller_err or "Invalid caller", is_error=True)
        target_spec, prompt, arg_err = _validate_consult_args(
            ident, args, packs
        )
        if arg_err is not None or target_spec is None:
            return Completed(arg_err or "invalid consult_peer", is_error=True)
        parent = await ledger.get_task(ident.task_id)
        if parent is None:
            return Completed("Parent task missing", is_error=True)
        child = await ledger.create_child_task(
            _build_consult_child_spec(parent, ctx, target_spec, prompt)
        )
        return await _execute_or_replay_consult(ledger, child, run_consult)

    return _handle_consult


def register_specialist_orchestration(
    runtime: NikaToolRuntime,
    ledger: NikaLedger,
    packs: Mapping[SpecialistId, SpecialistPack],
    run_consult: Callable[[TaskRecord], Awaitable[str | None]],
) -> None:
    existing = {spec.name for spec in runtime.catalog()}
    if "report_task" not in existing:
        runtime.register(
            REPORT_TASK_SPEC, _make_report_handler(runtime, ledger)
        )
    if "consult_peer" not in existing:
        runtime.register(
            CONSULT_PEER_SPEC,
            _make_consult_handler(runtime, ledger, packs, run_consult),
        )
