from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

import httpx
from nextloop import ModelProvider, SQLiteEventStore

from .db import NikaLedger
from .eval_runner import (
    EvalCaseResult,
    JudgeInput,
    judge_delivery,
    run_cases_bounded,
)
from .feishu import FeishuAdapter, FeishuInboundEvent, RecordedFeishuTransport
from .feishu_doc import InMemoryFeishuDocStore, register_feishu_doc_tools
from .packs import load_specialist_packs
from .pocket import (
    LocalPocketContractServer,
    PocketAdapter,
    PocketAdapterDeps,
    PocketRpcClient,
    PocketWebhookRequest,
    register_pocket_tools,
)
from .scheduler import ORCHESTRATION_TOOLS, NikaScheduler, SchedulerDeps
from .sessions import register_session_tools
from .tools import NikaToolRuntime
from .wiki import WikiMount, init_git_repo, register_wiki_tools
from .workspace import WorkspaceMount, register_workspace_tools

SEED_PRD = (
    "# Service PRD\n\n## Overview\nkeep overview\n\n"
    "## SLA\np99 latency <= 500ms\n\n## Appendix\nkeep appendix\n"
)


@dataclass(frozen=True)
class _Stage2Env:
    ledger: NikaLedger
    store: SQLiteEventStore
    http_client: httpx.AsyncClient
    transport: RecordedFeishuTransport
    doc_store: InMemoryFeishuDocStore
    pocket_srv: LocalPocketContractServer
    pocket_adapter: PocketAdapter
    sched: NikaScheduler
    feishu: FeishuAdapter

    async def close(self) -> None:
        await self.sched.close()
        await self.http_client.aclose()
        self.store.close()
        await self.ledger.close()


def _build_stage2_runtime(
    tmp: Path,
    store: SQLiteEventStore,
    ledger: NikaLedger,
    http_client: httpx.AsyncClient,
) -> tuple[NikaToolRuntime, InMemoryFeishuDocStore]:
    docs = InMemoryFeishuDocStore({"doc_prd": SEED_PRD})
    runtime = NikaToolRuntime()
    register_wiki_tools(runtime, WikiMount(tmp / "work", tmp / "personal"))
    register_session_tools(runtime, store, ledger)
    register_workspace_tools(runtime, WorkspaceMount(roots=(tmp,)))
    register_feishu_doc_tools(runtime, docs)
    register_pocket_tools(
        runtime, PocketRpcClient("http://pocket.local", "pkt_tok", http_client)
    )
    return runtime, docs


def _setup_stage2_env(
    tmp: Path,
    provider: ModelProvider,
    repo_root: Path,
    pocket_srv: LocalPocketContractServer,
) -> _Stage2Env:
    init_git_repo(
        tmp / "work", {"projects/a.md": "# A\n\n## Summary\ncore=v2\n"}
    )
    init_git_repo(tmp / "personal", {"notes/n.md": "# N\n"})
    ledger = NikaLedger(tmp / "nika.db")
    store = SQLiteEventStore(str(tmp / "nika.db"))
    client = httpx.AsyncClient(
        transport=pocket_srv.asgi_transport(), base_url="http://pocket.local"
    )
    tx = RecordedFeishuTransport()
    runtime, docs = _build_stage2_runtime(tmp, store, ledger, client)
    packs = load_specialist_packs(
        repo_root / "specialists",
        available_tools=[
            *(s.name for s in runtime.catalog()),
            *ORCHESTRATION_TOOLS,
        ],
        shared_skills_dir=repo_root / "skills",
    )
    p_adapter = PocketAdapter(
        PocketAdapterDeps("wh_sec", client, tx, "oc_owner_dm")
    )
    sched = NikaScheduler(
        SchedulerDeps(
            ledger=ledger,
            store=store,
            provider=provider,
            runtime=runtime,
            packs=packs,
            feishu_transport=tx,
            shared_skills_dir=repo_root / "skills",
            pocket_callback_sender=p_adapter.deliver_callback,
        )
    )
    p_adapter.bind_scheduler(sched)
    feishu = FeishuAdapter(scheduler=sched, allowlist=frozenset({"ou_eval"}))
    return _Stage2Env(
        ledger, store, client, tx, docs, pocket_srv, p_adapter, sched, feishu
    )


async def _f4_1_pocket_conflict_and_create(
    provider: ModelProvider, repo_root: Path
) -> tuple[bool, str]:
    srv = LocalPocketContractServer(agent_token="pkt_tok")
    srv.seed_event("ev_fixed", "2026-11-26", ("14:00", "15:00", "架构评审"))
    with tempfile.TemporaryDirectory() as td:
        env = _setup_stage2_env(Path(td), provider, repo_root, srv)
        try:
            q = (
                "查一下我 2026-11-26 14:00 到 15:00 有没有日程冲突；"
                "如果那个时段已经有会，告诉我撞了哪个会，并把新会议《预算对齐》"
                "建在 2026-11-26 15:30 到 16:30。"
            )
            await env.feishu.handle_event(
                FeishuInboundEvent("m_f4_1", "ou_eval", "oc_p1", text=q)
            )
            await env.sched.drain()
            reply = env.transport.final_card_texts[-1]
            created = [
                e
                for e in srv.events.values()
                if e["start_hhmm"] == "15:30" and e["end_hhmm"] == "16:30"
            ]
            if not created or "架构评审" not in reply:
                return False, f"events={srv.events} reply={reply!r}"
            verdict = await judge_delivery(
                provider,
                JudgeInput(
                    query=q,
                    evidence=(
                        f"Pocket 2026-11-26 events={list(srv.events.values())}; "
                        f"14:00-15:00 occupied by ev_fixed (架构评审), "
                        f"15:30-16:30 had no conflict and created {created[0]}"
                    ),
                    delivered_text=reply,
                ),
            )
            return (
                verdict.passed,
                f"created={created[0]['title']} judge={verdict.reason}",
            )
        finally:
            await env.close()


async def _f4_2_pocket_cloud_locked(
    provider: ModelProvider, repo_root: Path
) -> tuple[bool, str]:
    srv = LocalPocketContractServer(agent_token="pkt_tok")
    srv.seed_todo("td_alarm_0730", "07:30 起床闹钟", locked=True)
    with tempfile.TemporaryDirectory() as td:
        env = _setup_stage2_env(Path(td), provider, repo_root, srv)
        try:
            q = (
                "把 Pocket 里 todo_id 为 td_alarm_0730 "
                "的起床闹钟待办切换完成（toggle）。"
            )
            await env.feishu.handle_event(
                FeishuInboundEvent("m_f4_2", "ou_eval", "oc_p2", text=q)
            )
            await env.sched.drain()
            reply = env.transport.final_card_texts[-1]
            todo_state = srv.todos["td_alarm_0730"]
            if todo_state["done"] is not False:
                return False, "locked todo was mutated"
            verdict = await judge_delivery(
                provider,
                JudgeInput(
                    query=q,
                    evidence=(
                        "Pocket returned 409 CLOUD_LOCKED on single todo.toggle "
                        "attempt (agent did not retry); "
                        f"Todo 'td_alarm_0730' is locked on phone device; "
                        f"todo.list state={todo_state}. "
                        "User may unlock or modify it on the phone device."
                    ),
                    delivered_text=reply,
                    rubric=(
                        "Must honestly state the item is locked on phone "
                        "(CLOUD_LOCKED) and was NOT toggled."
                    ),
                ),
            )
            return verdict.passed, f"judge={verdict.reason} | {reply[:60]!r}"
        finally:
            await env.close()


async def _post_eval_delivery(
    env: _Stage2Env, did: str, cbk: str, prompt: str
) -> None:
    await env.pocket_adapter.handle_webhook(
        "Bearer wh_sec",
        PocketWebhookRequest(
            did,
            f"td_{did}",
            "@nika",
            prompt,
            "2026-11-26T08:00:00Z",
            f"http://pocket.local/v1/deliveries/{did}/result",
            cbk,
        ),
    )
    await env.sched.drain()


async def _f5_pocket_silent_boundary(
    provider: ModelProvider, repo_root: Path
) -> tuple[bool, str]:
    srv = LocalPocketContractServer(agent_token="pkt_tok")
    srv.seed_delivery("del_quiet", "cbk_q")
    srv.seed_delivery("del_exp", "cbk_e", status="EXPIRED")
    srv.seed_delivery("del_ping", "cbk_p")
    with tempfile.TemporaryDirectory() as td:
        env = _setup_stage2_env(Path(td), provider, repo_root, srv)
        try:
            await _post_eval_delivery(
                env,
                "del_quiet",
                "cbk_q",
                "读取 work 知识库 projects/a.md 的核心版本写回摘要，不要发飞书。",
            )
            if (
                srv.deliveries["del_quiet"]["status"] != "COMPLETED"
                or len(env.transport.created_cards) != 0
            ):
                return False, f"quiet leaked={env.transport.created_cards}"
            await _post_eval_delivery(
                env, "del_exp", "cbk_e", "一句话总结今日无事项，不要发飞书。"
            )
            if len(env.transport.created_cards) != 0:
                return False, "expired 409 triggered unexpected Feishu card"
            await _post_eval_delivery(
                env,
                "del_ping",
                "cbk_p",
                "请发飞书提醒我：今晚 20:00 提交季度复盘。",
            )
            ok = (
                srv.deliveries["del_ping"]["status"] == "COMPLETED"
                and len(env.transport.created_cards) == 1
            )
            return (
                ok,
                f"quiet=0, 409=0, reminder={len(env.transport.created_cards)}",
            )
        finally:
            await env.close()


async def _f6_feishu_doc_anchor_edit(
    provider: ModelProvider, repo_root: Path
) -> tuple[bool, str]:
    srv = LocalPocketContractServer(agent_token="pkt_tok")
    with tempfile.TemporaryDirectory() as td:
        env = _setup_stage2_env(Path(td), provider, repo_root, srv)
        try:
            q = (
                "把文档 doc_prd 的 SLA 章节改成 `p99 latency <= 180ms`，"
                "其他章节保持原样别动。"
            )
            await env.feishu.handle_event(
                FeishuInboundEvent(
                    message_id="m_f6",
                    actor_id="ou_eval",
                    chat_id="oc_doc",
                    comment_id="cmt_9",
                    doc_token="doc_prd",
                    anchor_paragraphs=("## SLA\np99 latency <= 500ms",),
                    text=q,
                )
            )
            await env.sched.drain()
            final_doc = await env.doc_store.read_doc("doc_prd")
            ok_doc = (
                "## Overview\nkeep overview" in final_doc
                and "## SLA\np99 latency <= 180ms" in final_doc
                and "## Appendix\nkeep appendix" in final_doc
                and len(env.transport.comment_replies) == 1
                and len(env.transport.created_cards) == 0
            )
            if not ok_doc:
                return False, f"doc={final_doc!r}"
            reply = env.transport.comment_replies[-1][2]
            verdict = await judge_delivery(
                provider,
                JudgeInput(
                    query=q,
                    evidence=(
                        "Tool returned: Updated doc_prd section '## SLA' "
                        "(read-back verified). Final section body: "
                        "`p99 latency <= 180ms`; Overview & Appendix unchanged."
                    ),
                    delivered_text=reply,
                ),
            )
            return verdict.passed, f"judge={verdict.reason} | {reply[:60]!r}"
        finally:
            await env.close()


async def run_stage2_evals(
    provider: ModelProvider, repo_root: Path
) -> list[EvalCaseResult]:
    return await run_cases_bounded(
        (
            (
                "F4",
                "F4.1_pocket_conflict_check_and_write",
                lambda: _f4_1_pocket_conflict_and_create(provider, repo_root),
            ),
            (
                "F4",
                "F4.2_pocket_409_cloud_locked_honest",
                lambda: _f4_2_pocket_cloud_locked(provider, repo_root),
            ),
            (
                "F5",
                "F5_pocket_webhook_silent_vs_alert_and_409",
                lambda: _f5_pocket_silent_boundary(provider, repo_root),
            ),
            (
                "F6",
                "F6_feishu_doc_comment_anchor_edit",
                lambda: _f6_feishu_doc_anchor_edit(provider, repo_root),
            ),
        )
    )
