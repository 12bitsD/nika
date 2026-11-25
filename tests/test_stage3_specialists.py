from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx
from nextloop import (
    CandidateRequest,
    FinishReason,
    ModelProvider,
    ModelResponse,
    SQLiteEventStore,
    ToolCall,
)

from nika.contracts import ReportStatus, SpecialistId, TaskKind, TaskStatus
from nika.db import ChildTaskSpec, NikaLedger
from nika.feishu import (
    FeishuAdapter,
    FeishuInboundEvent,
    RecordedFeishuTransport,
)
from nika.feishu_doc import InMemoryFeishuDocStore, register_feishu_doc_tools
from nika.packs import load_specialist_packs
from nika.pocket import (
    LocalPocketContractServer,
    PocketRpcClient,
    register_pocket_tools,
)
from nika.scheduler import ORCHESTRATION_TOOLS, NikaScheduler, SchedulerDeps
from nika.sessions import register_session_tools
from nika.tools import NikaToolRuntime
from nika.wiki import WikiMount, init_git_repo, register_wiki_tools
from nika.workspace import WorkspaceMount, register_workspace_tools

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass
class _Harness:
    ledger: NikaLedger
    sched: NikaScheduler
    feishu: FeishuAdapter
    tx: RecordedFeishuTransport


def _register_all_tools(
    tmp_path: Path,
    runtime: NikaToolRuntime,
    store: SQLiteEventStore,
    ledger: NikaLedger,
) -> None:
    init_git_repo(tmp_path / "work", {"a.md": "# A\n"})
    init_git_repo(tmp_path / "personal", {"b.md": "# B\n"})
    (tmp_path / "ws").mkdir(exist_ok=True)
    (tmp_path / "scratch").mkdir(exist_ok=True)
    register_wiki_tools(
        runtime,
        WikiMount(
            tmp_path / "work",
            tmp_path / "personal",
            scratch_roots=(tmp_path / "scratch",),
        ),
        extra_read_roots=(tmp_path / "ws", tmp_path / "scratch"),
    )
    register_session_tools(runtime, store, ledger)
    register_workspace_tools(
        runtime,
        WorkspaceMount(
            roots=(tmp_path / "ws",),
            scratch_roots=(tmp_path / "scratch",),
            denied_write_roots=(tmp_path / "work", tmp_path / "personal"),
        ),
    )
    register_feishu_doc_tools(runtime, InMemoryFeishuDocStore())


@asynccontextmanager
async def _stage3_harness(
    tmp_path: Path, provider: ModelProvider
) -> AsyncIterator[_Harness]:
    ledger = NikaLedger(tmp_path / "nika.db")
    store = SQLiteEventStore(str(tmp_path / "nika.db"))
    tx = RecordedFeishuTransport()
    runtime = NikaToolRuntime()
    _register_all_tools(tmp_path, runtime, store, ledger)
    srv = LocalPocketContractServer(agent_token="tok")
    async with httpx.AsyncClient(
        transport=srv.asgi_transport(), base_url="http://pocket.local"
    ) as client:
        register_pocket_tools(
            runtime, PocketRpcClient("http://pocket.local", "tok", client)
        )
        packs = load_specialist_packs(
            REPO_ROOT / "specialists",
            available_tools=[
                *(s.name for s in runtime.catalog()),
                *ORCHESTRATION_TOOLS,
            ],
            shared_skills_dir=REPO_ROOT / "skills",
        )
        sched = NikaScheduler(
            SchedulerDeps(
                ledger=ledger,
                store=store,
                provider=provider,
                runtime=runtime,
                packs=packs,
                feishu_transport=tx,
            )
        )
        feishu = FeishuAdapter(
            scheduler=sched, allowlist=frozenset({"ou_owner"})
        )
        try:
            yield _Harness(ledger=ledger, sched=sched, feishu=feishu, tx=tx)
        finally:
            await sched.close()
    store.close()
    await ledger.close()


async def test_all_five_specialist_packs_load_and_enforce_scopes(
    tmp_path: Path,
) -> None:
    ledger = NikaLedger(tmp_path / "nika.db")
    store = SQLiteEventStore(str(tmp_path / "nika.db"))
    runtime = NikaToolRuntime()
    _register_all_tools(tmp_path, runtime, store, ledger)
    srv = LocalPocketContractServer(agent_token="tok")
    async with httpx.AsyncClient(
        transport=srv.asgi_transport(), base_url="http://pocket.local"
    ) as client:
        register_pocket_tools(
            runtime, PocketRpcClient("http://pocket.local", "tok", client)
        )
        packs = load_specialist_packs(
            REPO_ROOT / "specialists",
            available_tools=[
                *(s.name for s in runtime.catalog()),
                *ORCHESTRATION_TOOLS,
            ],
            shared_skills_dir=REPO_ROOT / "skills",
        )
        assert set(packs.keys()) == {
            SpecialistId.MAIN,
            SpecialistId.TOP_TALENT,
            SpecialistId.CODER,
            SpecialistId.DOC_RESEARCH,
            SpecialistId.EVAL,
        }
        assert "bash" not in packs[SpecialistId.MAIN].tools
        assert "bash" not in packs[SpecialistId.DOC_RESEARCH].tools
        assert "write" not in packs[SpecialistId.EVAL].tools
        assert "wiki" not in packs[SpecialistId.TOP_TALENT].tools
        assert "bash" in packs[SpecialistId.CODER].tools
    store.close()
    await ledger.close()


def _coder_consult_step(request: CandidateRequest) -> ModelResponse:
    tool_msgs = [m.content or "" for m in request.messages if m.role == "tool"]
    if not tool_msgs:
        return ModelResponse(
            tool_calls=(
                ToolCall(
                    "nested_bad",
                    "consult_peer",
                    '{"specialist":"eval","artifact":"x","question":"y"}',
                ),
            ),
            finish_reason=FinishReason.TOOL_CALLS,
        )
    assert any("depth >= 1" in tm for tm in tool_msgs)
    return ModelResponse(
        content="BLIND_VERDICT: drop AbstractFactory, use plain dict.",
        finish_reason=FinishReason.STOP,
    )


class _ConsultAndDepthProvider:
    def __init__(self) -> None:
        self.consult_messages: list[tuple[str, ...]] = []

    async def complete(
        self,
        request: CandidateRequest,
        *,
        attempt: int,
        cancel: asyncio.Event,
    ) -> ModelResponse:
        del attempt, cancel
        sys_prompt = request.messages[0].content or ""
        if "你是 coder" in sys_prompt:
            self.consult_messages.append(
                tuple(m.content or "" for m in request.messages[1:])
            )
            return _coder_consult_step(request)
        if not any(m.role == "tool" for m in request.messages):
            args_json = (
                '{"specialist":"coder",'
                '"artifact":"class AbstractFactory: pass",'
                '"question":"too complex?"}'
            )
            return ModelResponse(
                tool_calls=(ToolCall("cp_1", "consult_peer", args_json),),
                finish_reason=FinishReason.TOOL_CALLS,
            )
        return ModelResponse(
            content="Adopted peer verdict: use plain dict.",
            finish_reason=FinishReason.STOP,
        )


async def test_consult_peer_clean_context_and_depth1_hard_cap(
    tmp_path: Path,
) -> None:
    provider = _ConsultAndDepthProvider()
    async with _stage3_harness(tmp_path, provider) as h:
        await h.feishu.handle_event(
            FeishuInboundEvent(
                "om_secret_chat",
                "ou_owner",
                "oc_c",
                thread_id="omt_c",
                text="PRIVATE_CHAT_TOKEN_991: review my design",
            )
        )
        await h.sched.drain()
        assert len(provider.consult_messages) == 2
        peer_seen = "\n".join(provider.consult_messages[0])
        assert "AbstractFactory" in peer_seen
        assert all(
            "PRIVATE_CHAT_TOKEN_991" not in "\n".join(m)
            for m in provider.consult_messages
        )
        tasks = await h.ledger.list_tasks_for_thread("feishu:thread:omt_c")
        consults = [t for t in tasks if t.kind == TaskKind.CONSULT]
        assert len(consults) == 1 and consults[0].depth == 1


class _FollowupAndHandoffProvider:
    def __init__(self) -> None:
        self.specialists_called: list[str] = []

    async def complete(
        self,
        request: CandidateRequest,
        *,
        attempt: int,
        cancel: asyncio.Event,
    ) -> ModelResponse:
        del attempt, cancel
        sys_p = request.messages[0].content or ""
        user_p = request.messages[-1].content or ""
        is_coder = "你是 coder" in sys_p
        self.specialists_called.append("coder" if is_coder else "main")
        if not is_coder:
            if "修代码" in user_p:
                return ModelResponse(
                    tool_calls=(
                        ToolCall(
                            "d_c",
                            "dispatch_task",
                            '{"specialist":"coder","goal":"fix module"}',
                        ),
                    ),
                    finish_reason=FinishReason.TOOL_CALLS,
                )
            return ModelResponse(
                content="main handled alarm", finish_reason=FinishReason.STOP
            )
        if "闹钟" in user_p:
            return ModelResponse(
                tool_calls=(
                    ToolCall(
                        "r_ho",
                        "report_task",
                        '{"status":"handoff","summary":"alarm for main"}',
                    ),
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            )
        return ModelResponse(
            tool_calls=(
                ToolCall(
                    "r_ok",
                    "report_task",
                    '{"status":"done","summary":"coder fixed it"}',
                ),
            ),
            finish_reason=FinishReason.TOOL_CALLS,
        )


async def test_thread_1hop_followup_and_handoff_back_to_main(
    tmp_path: Path,
) -> None:
    provider = _FollowupAndHandoffProvider()
    async with _stage3_harness(tmp_path, provider) as h:
        await h.feishu.handle_event(
            FeishuInboundEvent(
                "om_1", "ou_owner", "oc_1", thread_id="omt_h", text="修代码"
            )
        )
        await h.sched.drain()
        assert provider.specialists_called == ["main", "coder"]

        # Closed-thread follow-up routes 1-hop directly to coder
        provider.specialists_called.clear()
        await h.feishu.handle_event(
            FeishuInboundEvent(
                "om_2", "ou_owner", "oc_1", thread_id="omt_h", text="再补个断言"
            )
        )
        await h.sched.drain()
        assert provider.specialists_called == ["coder"]

        # Out-of-scope alarm request handoffs from coder -> main
        provider.specialists_called.clear()
        await h.feishu.handle_event(
            FeishuInboundEvent(
                "om_3",
                "ou_owner",
                "oc_1",
                thread_id="omt_h",
                text="顺便定个明早闹钟",
            )
        )
        await h.sched.drain()
        assert provider.specialists_called == ["coder", "main"]
        assert "main handled alarm" in h.tx.final_card_texts[-1]


def _coder_self_consult_step(
    tool_msgs: list[str],
) -> tuple[ModelResponse, str]:
    if not tool_msgs:
        args_json = '{"specialist":"coder","artifact":"x","question":"y"}'
        return (
            ModelResponse(
                tool_calls=(ToolCall("self_cp", "consult_peer", args_json),),
                finish_reason=FinishReason.TOOL_CALLS,
            ),
            "",
        )
    return (
        ModelResponse(
            tool_calls=(
                ToolCall(
                    "r_done",
                    "report_task",
                    '{"status":"done","summary":"checked"}',
                ),
            ),
            finish_reason=FinishReason.TOOL_CALLS,
        ),
        tool_msgs[-1],
    )


class _ConsultIsolationAndSelfBlockProvider:
    def __init__(self) -> None:
        self.consult_tool_names: tuple[str, ...] = ()
        self.self_consult_err: str = ""

    async def complete(
        self,
        request: CandidateRequest,
        *,
        attempt: int,
        cancel: asyncio.Event,
    ) -> ModelResponse:
        del attempt, cancel
        sys_p = request.messages[0].content or ""
        user_p = request.messages[-1].content or ""
        tool_msgs = [
            m.content or "" for m in request.messages if m.role == "tool"
        ]
        if "你是 coder" in sys_p and "[Peer Review Question]" in user_p:
            self.consult_tool_names = tuple(t.name for t in request.tools)
            return ModelResponse(
                content="read-only peer ok", finish_reason=FinishReason.STOP
            )
        if "你是 coder" in sys_p:
            resp, err = _coder_self_consult_step(tool_msgs)
            if err:
                self.self_consult_err = err
            return resp
        if "self_test" in user_p:
            return ModelResponse(
                tool_calls=(
                    ToolCall(
                        "d_self",
                        "dispatch_task",
                        '{"specialist":"coder","goal":"try self consult"}',
                    ),
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            )
        if not tool_msgs:
            args_json = (
                '{"specialist":"coder","artifact":"a=1","question":"ok?"}'
            )
            return ModelResponse(
                tool_calls=(ToolCall("cp_ro", "consult_peer", args_json),),
                finish_reason=FinishReason.TOOL_CALLS,
            )
        return ModelResponse(content="done", finish_reason=FinishReason.STOP)


async def test_stage3_blind_review_regressions(tmp_path: Path) -> None:
    provider = _ConsultIsolationAndSelfBlockProvider()
    async with _stage3_harness(tmp_path, provider) as h:
        await h.feishu.handle_event(
            FeishuInboundEvent(
                "om_ro", "ou_owner", "oc_r", thread_id="omt_r1", text="ro_check"
            )
        )
        await h.sched.drain()
        assert "write" not in provider.consult_tool_names
        assert "edit" not in provider.consult_tool_names
        assert "bash" not in provider.consult_tool_names
        assert "read" in provider.consult_tool_names

        await h.feishu.handle_event(
            FeishuInboundEvent(
                "om_sc",
                "ou_owner",
                "oc_r",
                thread_id="omt_r2",
                text="self_test",
            )
        )
        await h.sched.drain()
        assert "itself" in provider.self_consult_err


async def test_atomic_handoff_child_and_null_origin_cap(tmp_path: Path) -> None:
    ledger = NikaLedger(tmp_path / "nika.db")
    try:
        root = await ledger.create_child_task(
            ChildTaskSpec(
                parent_task_id="synthetic_root",
                origin_event_id=None,
                origin_call_id="c0",
                thread_key="feishu:thread:omt_atomic",
                kind=TaskKind.DISPATCH,
                specialist=SpecialistId.CODER,
                depth=0,
                prompt="alarm task",
                reply_target=None,
            )
        )
        await ledger.record_report(
            root.task_id, ReportStatus.HANDOFF, "reroute to main"
        )
        await ledger.settle_delivered(root.task_id, "fm_ho", "reroute to main")
        active = await ledger.get_active_task("feishu:thread:omt_atomic")
        ho_child = await ledger.get_handoff_child(root.task_id)
        assert active is not None and ho_child is not None
        assert active.task_id == ho_child.task_id
        assert ho_child.specialist == SpecialistId.MAIN
        assert ho_child.status == TaskStatus.QUEUED
        assert ho_child.origin_event_id == "synthetic_root"
        assert await ledger.count_handoffs(ho_child.origin_event_id) == 1
    finally:
        await ledger.close()
