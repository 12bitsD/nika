from __future__ import annotations

import asyncio
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from nextloop import ModelProvider, SQLiteEventStore

from .contracts import SpecialistId
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
from .scheduler import ORCHESTRATION_TOOLS, NikaScheduler, SchedulerDeps
from .sessions import register_session_tools
from .tools import NikaToolRuntime
from .wiki import (
    WikiMount,
    git_head_sha,
    init_git_repo,
    register_wiki_tools,
)
from .workspace import WorkspaceMount, register_workspace_tools


@dataclass(frozen=True)
class _Stage1Env:
    ledger: NikaLedger
    store: SQLiteEventStore
    transport: RecordedFeishuTransport
    sched: NikaScheduler
    feishu: FeishuAdapter
    work: Path

    async def close(self) -> None:
        await self.sched.close()
        self.store.close()
        await self.ledger.close()


def _setup_stage1_env(
    tmp: Path,
    provider: ModelProvider,
    repo_root: Path,
    work_files: Mapping[str, str],
) -> _Stage1Env:
    work = tmp / "work"
    init_git_repo(work, work_files)
    init_git_repo(
        tmp / "personal",
        {"notes/life.md": "# Life\n\n## Routine\ngym=07:30\n"},
    )
    ledger = NikaLedger(tmp / "nika.db")
    store = SQLiteEventStore(str(tmp / "nika.db"))
    transport = RecordedFeishuTransport()
    runtime = NikaToolRuntime()
    register_wiki_tools(
        runtime, WikiMount(work=work, personal=tmp / "personal")
    )
    register_session_tools(runtime, store, ledger)
    register_workspace_tools(runtime, WorkspaceMount(roots=(tmp,)))
    register_feishu_doc_tools(runtime, InMemoryFeishuDocStore())
    all_packs = load_specialist_packs(
        repo_root / "specialists",
        available_tools=[
            *(s.name for s in runtime.catalog()),
            "pocket",
            *ORCHESTRATION_TOOLS,
        ],
        shared_skills_dir=repo_root / "skills",
    )
    packs = {SpecialistId.MAIN: all_packs[SpecialistId.MAIN]}
    sched = NikaScheduler(
        SchedulerDeps(
            ledger=ledger,
            store=store,
            provider=provider,
            runtime=runtime,
            packs=packs,
            feishu_transport=transport,
            shared_skills_dir=repo_root / "skills",
        )
    )
    feishu = FeishuAdapter(scheduler=sched, allowlist=frozenset({"ou_eval"}))
    return _Stage1Env(ledger, store, transport, sched, feishu, work)


async def _f1_1_simple_qa(
    provider: ModelProvider, repo_root: Path
) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as td:
        env = _setup_stage1_env(
            Path(td), provider, repo_root, {"projects/a.md": "# A\n"}
        )
        try:
            q = "128 乘以 25 等于多少？直接回数字。"
            await env.feishu.handle_event(
                FeishuInboundEvent("m_f1_1", "ou_eval", "oc_1", text=q)
            )
            await env.sched.drain()
            tasks = await env.ledger.list_tasks_for_thread("feishu:dm:oc_1")
            reply = env.transport.final_card_texts[-1]
            if len(tasks) != 1 or "3200" not in reply:
                return False, f"tasks={len(tasks)} reply={reply!r}"
            verdict = await judge_delivery(
                provider,
                JudgeInput(
                    query=q,
                    evidence="pure arithmetic: 128 * 25 = 3200; zero dispatch",
                    delivered_text=reply,
                ),
            )
            return verdict.passed, f"reply={reply!r}"
        finally:
            await env.close()


async def _f1_2_ambiguous_aligns(
    provider: ModelProvider, repo_root: Path
) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as td:
        env = _setup_stage1_env(
            Path(td), provider, repo_root, {"projects/a.md": "# A\n"}
        )
        try:
            q = "帮我把同步策略改一下"
            await env.feishu.handle_event(
                FeishuInboundEvent("m_f1_2", "ou_eval", "oc_2", text=q)
            )
            await env.sched.drain()
            tasks = await env.ledger.list_tasks_for_thread("feishu:dm:oc_2")
            reply = env.transport.final_card_texts[-1]
            if len(tasks) != 1 or len(env.transport.created_cards) != 1:
                return (
                    False,
                    f"unexpected cards={len(env.transport.created_cards)}",
                )
            verdict = await judge_delivery(
                provider,
                JudgeInput(
                    query=q,
                    evidence=(
                        "No target or direction given; zero tools or writes executed. "
                        "Agent manages Wiki (work/personal), Pocket, Feishu docs, "
                        "and code configs, and refrained from direct edits."
                    ),
                    delivered_text=reply,
                    rubric=(
                        "Must ask concise clarification or options without "
                        "claiming changes were made."
                    ),
                ),
            )
            return verdict.passed, f"judge={verdict.reason} | {reply[:60]!r}"
        finally:
            await env.close()


async def _f1_3_heavy_dispatch(
    provider: ModelProvider, repo_root: Path
) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as td:
        env = _setup_stage1_env(
            Path(td), provider, repo_root, {"projects/a.md": "# A\n"}
        )
        try:
            q = (
                "去给 billing-repo 修复并发重复扣费的 bug，跑通 pytest 测试并清理死代码，"
                "禁止改动对外公开的 JSON 字段名。"
            )
            await env.feishu.handle_event(
                FeishuInboundEvent("m_f1_3", "ou_eval", "oc_3", text=q)
            )
            await env.sched.drain()
            dispatched = await env.ledger.list_tasks_for_thread(
                "feishu:thread:card_1"
            )
            if not dispatched or len(env.transport.created_cards) != 1:
                return (
                    False,
                    f"no dispatch; cards={env.transport.created_cards}",
                )
            child = dispatched[0]
            ok = (
                child.specialist.value == "coder"
                and "pytest" in child.prompt.lower()
                and "json" in child.prompt.lower()
            )
            return (
                ok,
                f"specialist={child.specialist.value} goal={child.prompt[:80]!r}",
            )
        finally:
            await env.close()


async def _verify_wiki_upsert_and_revert(env: _Stage1Env) -> tuple[bool, str]:
    q_up = (
        "把新结论写入 work 知识库的 projects/cache-rule.md："
        "默认 TTL 为 1800 秒。"
    )
    await env.feishu.handle_event(
        FeishuInboundEvent("m_f2_2", "ou_eval", "oc_w2", text=q_up)
    )
    await env.sched.drain()
    r2 = env.transport.final_card_texts[-1]
    head_sha = await asyncio.to_thread(git_head_sha, env.work)
    created_file = env.work / "projects" / "cache-rule.md"
    if not created_file.is_file() or head_sha not in r2:
        return False, f"file={created_file.is_file()} sha={head_sha} r={r2!r}"
    q_rev = f"把 work 知识库里刚才那笔提交 {head_sha} 撤回。"
    await env.feishu.handle_event(
        FeishuInboundEvent("m_f2_3", "ou_eval", "oc_w3", text=q_rev)
    )
    await env.sched.drain()
    if created_file.exists():
        return False, "cache-rule.md still exists after revert"
    return True, f"9477 found, {head_sha} committed & reverted cleanly"


async def _f2_wiki_search_upsert_revert(
    provider: ModelProvider, repo_root: Path
) -> tuple[bool, str]:
    doc = (
        "---\nid: project-tcc\n---\n# TCC\n\n"
        "## Background\nintro text\n\n"
        "## Runtime Limits\ngrpc_port = 9477\nmax_retries = 6\n"
    )
    with tempfile.TemporaryDirectory() as td:
        env = _setup_stage1_env(
            Path(td), provider, repo_root, {"projects/tcc.md": doc}
        )
        try:
            q_search = "查一下知识库里 TCC 的 grpc_port 是多少？只回答端口号。"
            await env.feishu.handle_event(
                FeishuInboundEvent("m_f2_1", "ou_eval", "oc_w1", text=q_search)
            )
            await env.sched.drain()
            r1 = env.transport.final_card_texts[-1]
            if "9477" not in r1:
                return False, f"search/read missed 9477: {r1!r}"
            return await _verify_wiki_upsert_and_revert(env)
        finally:
            await env.close()


async def _f3_cross_entry_recall(
    provider: ModelProvider, repo_root: Path
) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as td:
        env = _setup_stage1_env(
            Path(td), provider, repo_root, {"projects/a.md": "# A\n"}
        )
        try:
            seed_q = (
                "记一下我们刚敲定的限流参数：窗口 60 秒，上限 450 次，"
                "前缀 rl:v3:。回复收到即可。"
            )
            await env.feishu.handle_event(
                FeishuInboundEvent(
                    "m_f3_seed",
                    "ou_eval",
                    "oc_dm",
                    thread_id="omt_prev_topic",
                    text=seed_q,
                )
            )
            await env.sched.drain()
            now_q = (
                "按刚才另一个话题里敲定的限流参数，"
                "写进 work 知识库的 projects/ratelimit.md。"
            )
            await env.feishu.handle_event(
                FeishuInboundEvent(
                    "m_f3_now", "ou_eval", "oc_fresh", text=now_q
                )
            )
            await env.sched.drain()
            target_doc = env.work / "projects" / "ratelimit.md"
            if not target_doc.is_file():
                return False, "projects/ratelimit.md was not created"
            body = target_doc.read_text(encoding="utf-8")
            ok = "450" in body and "rl:v3:" in body
            return ok, f"recalled & wrote body={body.strip()[:90]!r}"
        finally:
            await env.close()


async def run_stage1_evals(
    provider: ModelProvider, repo_root: Path
) -> list[EvalCaseResult]:
    return await run_cases_bounded(
        (
            (
                "F1",
                "F1.1_simple_qa_no_dispatch",
                lambda: _f1_1_simple_qa(provider, repo_root),
            ),
            (
                "F1",
                "F1.2_ambiguous_aligns",
                lambda: _f1_2_ambiguous_aligns(provider, repo_root),
            ),
            (
                "F1",
                "F1.3_heavy_dispatches_coder",
                lambda: _f1_3_heavy_dispatch(provider, repo_root),
            ),
            (
                "F2",
                "F2_dual_wiki_search_upsert_revert",
                lambda: _f2_wiki_search_upsert_revert(provider, repo_root),
            ),
            (
                "F3",
                "F3_cross_entry_session_recall",
                lambda: _f3_cross_entry_recall(provider, repo_root),
            ),
        )
    )
