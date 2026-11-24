from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from nextloop import (
    CandidateRequest,
    FinishReason,
    ModelProvider,
    ModelResponse,
    SQLiteEventStore,
    ToolCall,
)

from nika.contracts import (
    IngressEnvelope,
    IngressSource,
    ReplyKind,
    ReplyTarget,
    ReportStatus,
    SpecialistId,
    TaskStatus,
)
from nika.db import NikaLedger
from nika.feishu import (
    FeishuAdapter,
    FeishuInboundEvent,
    LiveStatusCardSession,
    RecordedFeishuTransport,
)
from nika.packs import load_specialist_packs
from nika.scheduler import ORCHESTRATION_TOOLS, NikaScheduler, SchedulerDeps
from nika.sessions import register_session_tools
from nika.tools import NikaToolRuntime
from nika.wiki import WikiMount, init_git_repo, register_wiki_tools

REPO_ROOT = Path(__file__).resolve().parent.parent


class ScriptedProvider:
    def __init__(
        self,
        responses: list[ModelResponse],
        on_call: Callable[[int], None] | None = None,
    ) -> None:
        self._responses = list(responses)
        self._on_call = on_call
        self.requests: list[CandidateRequest] = []

    async def complete(
        self,
        request: CandidateRequest,
        *,
        attempt: int,
        cancel: asyncio.Event,
    ) -> ModelResponse:
        del attempt
        self.requests.append(request)
        if self._on_call is not None:
            self._on_call(len(self.requests))
        if cancel.is_set():
            return ModelResponse(finish_reason=FinishReason.CANCELLED)
        if not self._responses:
            return ModelResponse(content="ok", finish_reason=FinishReason.STOP)
        return self._responses.pop(0)


class SlowProvider:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def complete(
        self,
        request: CandidateRequest,
        *,
        attempt: int,
        cancel: asyncio.Event,
    ) -> ModelResponse:
        del request, attempt
        self.started.set()
        await cancel.wait()
        return ModelResponse(finish_reason=FinishReason.CANCELLED)


@dataclass(frozen=True)
class _TestHarness:
    ledger: NikaLedger
    store: SQLiteEventStore
    transport: RecordedFeishuTransport
    runtime: NikaToolRuntime
    scheduler: NikaScheduler
    feishu: FeishuAdapter

    async def close(self) -> None:
        await self.scheduler.close()
        self.store.close()
        await self.ledger.close()


def _make_harness(
    tmp_path: Path,
    provider: ModelProvider,
    clock: Callable[[], float] | None = None,
) -> _TestHarness:
    init_git_repo(tmp_path / "work", {"projects/p.md": "# P\n## Info\nx=1\n"})
    init_git_repo(tmp_path / "personal", {"notes/n.md": "# N\n"})
    ledger = NikaLedger(tmp_path / "nika.db")
    store = SQLiteEventStore(str(tmp_path / "nika.db"))
    transport = RecordedFeishuTransport()
    runtime = NikaToolRuntime()
    register_wiki_tools(
        runtime,
        WikiMount(work=tmp_path / "work", personal=tmp_path / "personal"),
    )
    register_session_tools(runtime, store, ledger)
    packs = load_specialist_packs(
        REPO_ROOT / "specialists",
        available_tools=[
            *(s.name for s in runtime.catalog()),
            *ORCHESTRATION_TOOLS,
        ],
        shared_skills_dir=REPO_ROOT / "skills",
    )
    deps = SchedulerDeps(
        ledger=ledger,
        store=store,
        provider=provider,
        runtime=runtime,
        packs=packs,
        feishu_transport=transport,
        shared_skills_dir=REPO_ROOT / "skills",
        clock=clock or asyncio.get_running_loop().time,
    )
    scheduler = NikaScheduler(deps)
    return _TestHarness(
        ledger,
        store,
        transport,
        runtime,
        scheduler,
        FeishuAdapter(scheduler=scheduler, allowlist=frozenset({"ou_owner"})),
    )


async def test_ledger_dedupe_and_single_active_task_race(
    tmp_path: Path,
) -> None:
    ledger = NikaLedger(tmp_path / "nika.db")
    try:
        target = ReplyTarget(kind=ReplyKind.FEISHU_CARD, channel_id="oc_1")
        env1 = IngressEnvelope(
            event_id="feishu:om_1",
            source=IngressSource.FEISHU,
            thread_key="feishu:dm:oc_1",
            prompt="first",
            reply_target=target,
        )
        env2 = IngressEnvelope(
            event_id="feishu:om_2",
            source=IngressSource.FEISHU,
            thread_key="feishu:dm:oc_1",
            prompt="second racing",
            reply_target=target,
        )
        d1 = await ledger.accept_ingress(env1)
        d_dup = await ledger.accept_ingress(env1)
        d2 = await ledger.accept_ingress(env2)
        assert d1.action == "start_new"
        assert d_dup.action == "duplicate"
        assert d2.action == "steer_active"
        assert d1.task is not None and d2.task is not None
        assert d2.task.task_id == d1.task.task_id
    finally:
        await ledger.close()


async def test_dual_wiki_search_guard_and_pack_load(tmp_path: Path) -> None:
    work_repo = tmp_path / "work"
    personal_repo = tmp_path / "personal"
    init_git_repo(
        work_repo,
        {
            "AGENTS.md": "# protected\n",
            "projects/alpha.md": (
                "---\nid: project-alpha\n---\n# Alpha\n\n"
                "## Overview\nline1\n\n## Limits\nport=9477\nretry=3\n"
            ),
        },
    )
    init_git_repo(personal_repo, {"notes/reading.md": "# Reading\n"})
    runtime = NikaToolRuntime()
    register_wiki_tools(
        runtime, WikiMount(work=work_repo, personal=personal_repo)
    )
    packs = load_specialist_packs(
        REPO_ROOT / "specialists",
        available_tools=[
            *(s.name for s in runtime.catalog()),
            "session_ctl",
            *ORCHESTRATION_TOOLS,
        ],
    )
    assert SpecialistId.MAIN in packs
    search_out = await runtime.invoke_direct(
        "wiki", {"action": "search", "query": "9477", "repo": "all"}
    )
    assert "work:projects/alpha.md" in search_out.content
    assert "## Limits" in search_out.content
    blocked = await runtime.invoke_direct(
        "wiki",
        {
            "action": "upsert",
            "repo": "work",
            "path": "AGENTS.md",
            "content": "hacked",
            "message": "bad",
        },
    )
    assert blocked.is_error is True


async def test_dual_wiki_upsert_and_revert_roundtrip(tmp_path: Path) -> None:
    work_repo = tmp_path / "work"
    personal_repo = tmp_path / "personal"
    init_git_repo(work_repo, {"projects/alpha.md": "# Alpha\n"})
    init_git_repo(personal_repo, {"notes/reading.md": "# Reading\n"})
    runtime = NikaToolRuntime()
    register_wiki_tools(
        runtime, WikiMount(work=work_repo, personal=personal_repo)
    )
    upserted = await runtime.invoke_direct(
        "wiki",
        {
            "action": "upsert",
            "repo": "work",
            "path": "projects/beta.md",
            "content": "# Beta\nval=42\n",
            "message": "add beta",
        },
    )
    assert upserted.is_error is False
    rev = upserted.content.split("rev ")[-1].strip().split()[0]
    assert (work_repo / "projects" / "beta.md").is_file()
    reverted = await runtime.invoke_direct(
        "wiki", {"action": "revert", "repo": "work", "rev": rev}
    )
    assert reverted.is_error is False
    assert not (work_repo / "projects" / "beta.md").exists()


async def test_live_status_card_throttles_burst_patches() -> None:
    tx = RecordedFeishuTransport()
    now_t = [10.0]
    card = LiveStatusCardSession(
        transport=tx, channel_id="oc_t", clock=lambda: now_t[0]
    )
    await card.emit_progress("step 1")
    now_t[0] = 10.6
    await card.emit_progress("step 2 burst")
    now_t[0] = 11.4
    await card.emit_progress("step 3 burst")
    assert len(tx.patched_cards) == 0
    now_t[0] = 12.1
    await card.emit_progress("step 4 allowed")
    assert len(tx.patched_cards) == 1
    await card.finalize("done")
    assert tx.final_card_texts[-1] == "done"


async def test_feishu_allowlist_turn_and_session_recall(tmp_path: Path) -> None:
    clock_now = [100.0]
    provider = ScriptedProvider(
        [
            ModelResponse(
                tool_calls=(
                    ToolCall(
                        call_id="c1",
                        name="wiki",
                        arguments='{"action":"search","query":"x=1","repo":"work"}',
                    ),
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            ),
            ModelResponse(
                content="查到了：x=1",
                finish_reason=FinishReason.STOP,
            ),
        ],
        on_call=lambda idx: clock_now.__setitem__(0, 100.0 + idx * 3.0),
    )
    h = _make_harness(tmp_path, provider, clock=lambda: clock_now[0])
    try:
        denied = await h.feishu.handle_event(
            FeishuInboundEvent("om_unauth", "ou_stranger", "oc_dm", text="hi")
        )
        assert denied is False
        assert len(provider.requests) == 0

        accepted = await h.feishu.handle_event(
            FeishuInboundEvent("om_ok1", "ou_owner", "oc_dm", text="查一下 P")
        )
        assert accepted is True
        await h.scheduler.drain()
        assert len(h.transport.created_cards) == 1
        assert any("Step 2" in txt for _, txt in h.transport.patched_cards)
        assert "x=1" in h.transport.final_card_texts[-1]

        recent_out = await h.runtime.invoke_direct(
            "session_ctl", {"action": "recent"}
        )
        assert "查到了：x=1" in recent_out.content
        assert "feishu:dm:oc_dm" in recent_out.content
    finally:
        await h.close()


async def test_feishu_stop_cancels_active_turn(tmp_path: Path) -> None:
    slow = SlowProvider()
    h = _make_harness(tmp_path, slow)
    try:
        await h.feishu.handle_event(
            FeishuInboundEvent(
                "om_slow", "ou_owner", "oc_dm", thread_id="omt_s", text="慢任务"
            )
        )
        await asyncio.wait_for(slow.started.wait(), timeout=2.0)
        stopped = await h.feishu.handle_event(
            FeishuInboundEvent(
                "om_stop", "ou_owner", "oc_dm", thread_id="omt_s", text="/stop"
            )
        )
        assert stopped is True
        await h.scheduler.drain()
        tasks = await h.ledger.list_tasks_for_thread("feishu:thread:omt_s")
        assert tasks[-1].status == TaskStatus.FAILED

        h.scheduler.set_provider(
            ScriptedProvider(
                [ModelResponse(content="ok2", finish_reason=FinishReason.STOP)]
            )
        )
        await h.feishu.handle_event(
            FeishuInboundEvent(
                "om_next", "ou_owner", "oc_dm", thread_id="omt_s", text="新问题"
            )
        )
        await h.scheduler.drain()
        after = await h.ledger.list_tasks_for_thread("feishu:thread:omt_s")
        assert len(after) == 2 and after[-1].status == TaskStatus.DONE
    finally:
        await h.close()


async def test_wiki_blocks_dotdot_casefold_symlink_and_protected_revert(
    tmp_path: Path,
) -> None:
    work_repo = tmp_path / "work"
    seed_rev = init_git_repo(
        work_repo,
        {"AGENTS.md": "# protected\n", "projects/alpha.md": "# Alpha\n"},
    )
    init_git_repo(tmp_path / "personal", {"notes/n.md": "# N\n"})
    (work_repo / "notes").mkdir(parents=True, exist_ok=True)
    (work_repo / "notes" / "sym.md").symlink_to(work_repo / "AGENTS.md")
    runtime = NikaToolRuntime()
    register_wiki_tools(
        runtime, WikiMount(work=work_repo, personal=tmp_path / "personal")
    )
    bad_paths = (
        "notes/../.git/config",
        "notes/../AGENTS.md",
        "agents.md",
        ".",
        "notes/sym.md",
    )
    results = [
        await runtime.invoke_direct(
            "wiki",
            {"action": "upsert", "repo": "work", "path": p, "content": "x"},
        )
        for p in bad_paths
    ]
    assert all(r.is_error for r in results)
    rev_res = await runtime.invoke_direct(
        "wiki", {"action": "revert", "repo": "work", "rev": seed_rev}
    )
    assert rev_res.is_error is True and (work_repo / "AGENTS.md").is_file()
    null_read = await runtime.invoke_direct(
        "read",
        {
            "path": "work:projects/alpha.md",
            "start_line": None,
            "end_line": None,
        },
    )
    assert null_read.is_error is False and "# Alpha" in null_read.content


def _write_dispatch_packs(specs_dir: Path) -> None:
    (specs_dir / "_shared").mkdir(parents=True)
    (specs_dir / "_shared" / "RED_LINES.md").write_text("red\n")
    (specs_dir / "main").mkdir()
    (specs_dir / "main" / "pack.toml").write_text(
        'schema = "nika.specialist/v1"\nname = "main"\n'
        'min_nextloop = "1.1.0rc1"\nevent_schema = "1.1"\n'
        'tools = ["dispatch_task"]\n'
    )
    (specs_dir / "main" / "prompt.md").write_text("main\n")
    (specs_dir / "coder").mkdir()
    (specs_dir / "coder" / "pack.toml").write_text(
        'schema = "nika.specialist/v1"\nname = "coder"\n'
        'min_nextloop = "1.1.0rc1"\nevent_schema = "1.1"\ntools = []\n'
    )
    (specs_dir / "coder" / "prompt.md").write_text("coder\n")


class _RoutingTestProvider:
    def __init__(self, slow_coder: SlowProvider) -> None:
        self.slow_coder = slow_coder
        self.coder_block = True

    async def complete(
        self,
        request: CandidateRequest,
        *,
        attempt: int,
        cancel: asyncio.Event,
    ) -> ModelResponse:
        sys_text = request.messages[0].content or ""
        if "coder" in sys_text:
            if self.coder_block:
                return await self.slow_coder.complete(
                    request, attempt=attempt, cancel=cancel
                )
            return ModelResponse(
                content="coder done", finish_reason=FinishReason.STOP
            )
        return ModelResponse(
            tool_calls=(
                ToolCall(
                    call_id="d1",
                    name="dispatch_task",
                    arguments='{"specialist":"coder","goal":"fix bug"}',
                ),
            ),
            finish_reason=FinishReason.TOOL_CALLS,
        )


async def test_dispatch_preserves_child_active_task_and_single_dm_card(
    tmp_path: Path,
) -> None:
    _write_dispatch_packs(tmp_path / "specialists")
    ledger = NikaLedger(tmp_path / "nika.db")
    store = SQLiteEventStore(str(tmp_path / "nika.db"))
    tx = RecordedFeishuTransport()
    packs = load_specialist_packs(
        tmp_path / "specialists", available_tools=ORCHESTRATION_TOOLS
    )
    router = _RoutingTestProvider(SlowProvider())
    sched = NikaScheduler(
        SchedulerDeps(
            ledger=ledger,
            store=store,
            provider=router,
            runtime=NikaToolRuntime(),
            packs=packs,
            feishu_transport=tx,
        )
    )
    feishu = FeishuAdapter(scheduler=sched, allowlist=frozenset({"ou_owner"}))
    try:
        await feishu.handle_event(
            FeishuInboundEvent(
                "om_t1", "ou_owner", "oc_dm", thread_id="omt_ex", text="修 bug"
            )
        )
        await asyncio.wait_for(router.slow_coder.started.wait(), timeout=2.0)
        await asyncio.sleep(0.05)
        active = await ledger.get_active_task("feishu:thread:omt_ex")
        assert active is not None and active.specialist == SpecialistId.CODER
        await sched.stop("feishu:thread:omt_ex")
        await sched.drain()

        router.coder_block = False
        await feishu.handle_event(
            FeishuInboundEvent("om_dm1", "ou_owner", "oc_dm2", text="修 bug")
        )
        await sched.drain()
        dm2_cards = [c for c in tx.created_cards if c[1] == "oc_dm2"]
        assert len(dm2_cards) == 1
    finally:
        await sched.close()
        store.close()
        await ledger.close()


async def test_queued_steer_and_resume_decision_delivery(
    tmp_path: Path,
) -> None:
    seen_prompts: list[str] = []

    class RecordingProvider:
        async def complete(
            self,
            request: CandidateRequest,
            *,
            attempt: int,
            cancel: asyncio.Event,
        ) -> ModelResponse:
            del attempt, cancel
            joined = "\n".join(m.content or "" for m in request.messages)
            seen_prompts.append(joined)
            await asyncio.sleep(0.03)
            return ModelResponse(
                content="done", finish_reason=FinishReason.STOP
            )

    h = _make_harness(tmp_path, RecordingProvider())
    try:
        target = ReplyTarget(kind=ReplyKind.FEISHU_CARD, channel_id="oc_q")
        await h.scheduler.ingest(
            IngressEnvelope(
                "feishu:q1",
                IngressSource.FEISHU,
                "feishu:dm:oc_q",
                "first_msg",
                target,
            )
        )
        await h.scheduler.ingest(
            IngressEnvelope(
                "feishu:q2",
                IngressSource.FEISHU,
                "feishu:dm:oc_q",
                "second_queued_msg",
                target,
            )
        )
        await h.scheduler.drain()
        combined = "\n".join(seen_prompts)
        assert "first_msg" in combined and "second_queued_msg" in combined
    finally:
        await h.close()


async def test_live_card_finalized_guard_and_skill_allowlist(
    tmp_path: Path,
) -> None:
    tx = RecordedFeishuTransport()
    now_t = [10.0]
    card = LiveStatusCardSession(
        transport=tx, channel_id="oc_f", clock=lambda: now_t[0]
    )
    await card.finalize("final answer")
    now_t[0] = 25.0
    await card.emit_progress("stale late progress")
    assert tx.final_card_texts[-1] == "final answer"

    extra_skills = tmp_path / "skills"
    (extra_skills / "wiki").mkdir(parents=True)
    (extra_skills / "wiki" / "SKILL.md").write_text(
        "---\nname: wiki\ndescription: w\nrequires_tools: [wiki, read]\n---\nbody\n"
    )
    (extra_skills / "secret_other").mkdir(parents=True)
    (extra_skills / "secret_other" / "SKILL.md").write_text(
        "---\nname: secret_other\ndescription: s\n---\nbody\n"
    )
    packs = load_specialist_packs(
        REPO_ROOT / "specialists",
        available_tools=("wiki", "read", "session_ctl", "dispatch_task"),
        shared_skills_dir=extra_skills,
    )
    reg = packs[SpecialistId.MAIN].skill_registry
    assert reg is not None
    assert [s.name for s in reg.list()] == ["wiki"]


async def test_resume_decision_runs_fresh_turn_not_replay(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    class TwoTurnProvider:
        async def complete(
            self,
            request: CandidateRequest,
            *,
            attempt: int,
            cancel: asyncio.Event,
        ) -> ModelResponse:
            del attempt, cancel
            calls.append(request.messages[-1].content or "")
            return ModelResponse(content="ans", finish_reason=FinishReason.STOP)

    h = _make_harness(tmp_path, TwoTurnProvider())
    try:
        await h.feishu.handle_event(
            FeishuInboundEvent("om_r1", "ou_owner", "oc_r", text="turn1_ask")
        )
        await h.scheduler.drain()
        tasks = await h.ledger.list_tasks_for_thread("feishu:dm:oc_r")
        tid = tasks[0].task_id
        # Simulate task paused at NEED_DECISION on active thread
        await h.ledger.record_report(
            tid, ReportStatus.NEED_DECISION, "pick one"
        )
        await h.ledger.settle_delivered(tid, "fm_1", "pick one")
        with h.ledger._write_tx() as conn:
            conn.execute(
                "UPDATE threads SET active_task_id = ? WHERE thread_key = ?",
                (tid, "feishu:dm:oc_r"),
            )
        await h.feishu.handle_event(
            FeishuInboundEvent("om_r2", "ou_owner", "oc_r", text="turn2_choice")
        )
        await h.scheduler.drain()
        assert "turn1_ask" in calls and "turn2_choice" in calls
    finally:
        await h.close()
