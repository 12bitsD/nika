from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from nextloop import (
    CandidateRequest,
    Completed,
    FinishReason,
    ModelResponse,
    SQLiteEventStore,
    ToolCall,
)

from nika.contracts import SessionIdentity, SpecialistId, TaskKind
from nika.db import NikaLedger
from nika.feishu import RecordedFeishuTransport
from nika.feishu_doc import InMemoryFeishuDocStore, register_feishu_doc_tools
from nika.packs import load_specialist_packs
from nika.pocket import (
    LocalPocketContractServer,
    PocketAdapter,
    PocketAdapterDeps,
    PocketRpcClient,
    PocketWebhookRequest,
    register_pocket_tools,
)
from nika.scheduler import ORCHESTRATION_TOOLS, NikaScheduler, SchedulerDeps
from nika.sessions import register_session_tools
from nika.tools import NikaToolRuntime
from nika.wiki import WikiMount, init_git_repo, register_wiki_tools
from nika.workspace import WorkspaceMount, register_workspace_tools

REPO_ROOT = Path(__file__).resolve().parent.parent


async def test_workspace_edit_write_grep_and_path_guards(
    tmp_path: Path,
) -> None:
    ws = tmp_path / "ws"
    scratch = tmp_path / "scratch"
    ws.mkdir()
    scratch.mkdir()
    (ws / "AGENTS.md").write_text("# guard\n")
    runtime = NikaToolRuntime()
    register_workspace_tools(
        runtime, WorkspaceMount(roots=(ws,), scratch_roots=(scratch,))
    )
    w_ok = await runtime.invoke_direct(
        "write", {"path": str(ws / "calc.py"), "content": "x = 1\ny = 2\n"}
    )
    e_ok = await runtime.invoke_direct(
        "edit",
        {"path": str(ws / "calc.py"), "old_text": "x = 1", "new_text": "x = 9"},
    )
    g_ok = await runtime.invoke_direct(
        "grep", {"pattern": "x = 9", "path": str(ws)}
    )
    assert not w_ok.is_error and not e_ok.is_error and "calc.py" in g_ok.content

    blocked = await runtime.invoke_direct(
        "write", {"path": str(ws / "AGENTS.md"), "content": "bad"}
    )
    assert blocked.is_error is True

    tt_scope = runtime.scope(
        SessionIdentity(
            "s_tt", "t_tt", SpecialistId.TOP_TALENT, TaskKind.DISPATCH
        ),
        frozenset({"write"}),
    )
    denied_ws = await tt_scope.execute(
        ToolCall("c1", "write", "{}"),
        {"path": str(ws / "nope.py"), "content": "1"},
        session_id="s_tt",
        turn=1,
        step=1,
        cancel=asyncio.Event(),
    )
    assert getattr(denied_ws, "is_error", False) is True


async def test_workspace_bash_strips_secrets_and_kills_process_group(
    tmp_path: Path,
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    runtime = NikaToolRuntime()
    fake_env = {
        "PATH": "/usr/bin:/bin",
        "SAFE_KEY": "ok_visible",
        "NIKA_API_KEY": "secret_1",
        "FEISHU_APP_SECRET": "secret_2",
        "POCKET_TOKEN": "secret_3",
    }
    register_workspace_tools(
        runtime, WorkspaceMount(roots=(ws,)), base_env=fake_env
    )
    env_out = await runtime.invoke_direct("bash", {"command": "env"})
    assert "SAFE_KEY=ok_visible" in env_out.content
    assert "secret_1" not in env_out.content
    assert "secret_2" not in env_out.content
    assert "secret_3" not in env_out.content

    pid_file = ws / "grandchild.pid"
    cmd = f"/bin/sleep 30 & echo $! > {pid_file}; /bin/sleep 30"
    timed_out = await runtime.invoke_direct(
        "bash", {"command": cmd, "timeout_seconds": 0.35}
    )
    assert timed_out.is_error is True
    grand_pid = int(pid_file.read_text().strip())
    await asyncio.sleep(0.05)
    with pytest.raises(ProcessLookupError):
        os.kill(grand_pid, 0)


async def test_feishu_doc_replace_section_and_mandatory_readback() -> None:
    initial = (
        "# Architecture\n\n## Intro\nkeep intro\n\n"
        "## Rollout\nold rollout\n\n## Risks\nkeep risks\n"
    )
    doc_store = InMemoryFeishuDocStore({"doc_1": initial})
    runtime = NikaToolRuntime()
    register_feishu_doc_tools(runtime, doc_store)

    ok = await runtime.invoke_direct(
        "feishu_doc",
        {
            "action": "replace_section",
            "doc_token": "doc_1",
            "heading": "Rollout",
            "content": "canary 10% -> 100%",
        },
    )
    assert ok.is_error is False
    updated = await doc_store.read_doc("doc_1")
    assert "## Intro\nkeep intro" in updated
    assert "## Rollout\ncanary 10% -> 100%" in updated
    assert "## Risks\nkeep risks" in updated

    doc_store.drop_writes()
    failed = await runtime.invoke_direct(
        "feishu_doc",
        {
            "action": "replace_section",
            "doc_token": "doc_1",
            "heading": "Rollout",
            "content": "silent drop attempt",
        },
    )
    assert failed.is_error is True
    assert "read-back" in failed.content.lower()


async def test_pocket_rpc_idempotency_conflict_and_cloud_locked() -> None:
    server = LocalPocketContractServer(agent_token="pkt_tok")
    server.seed_event("ev_1", "2026-11-25", ("09:00", "10:00", "Standup"))
    server.seed_todo("td_lock", "Wake alarm", locked=True)
    async with httpx.AsyncClient(
        transport=server.asgi_transport(), base_url="http://pocket.local"
    ) as client:
        runtime = NikaToolRuntime()
        register_pocket_tools(
            runtime, PocketRpcClient("http://pocket.local", "pkt_tok", client)
        )
        params = {
            "event_date": "2026-11-25",
            "start_hhmm": "09:30",
            "end_hhmm": "10:30",
            "title": "Overlap",
        }
        s1 = await runtime.invoke_direct(
            "pocket", {"method": "event.set", "params": params}
        )
        s2 = await runtime.invoke_direct(
            "pocket", {"method": "event.set", "params": params}
        )
        assert s1.is_error is False and s1.content == s2.content
        listed = await runtime.invoke_direct(
            "pocket",
            {
                "method": "event.list",
                "params": {
                    "start_date": "2026-11-25",
                    "end_date": "2026-11-25",
                },
            },
        )
        assert '"has_conflict": true' in listed.content.lower()
        locked_res = await runtime.invoke_direct(
            "pocket",
            {"method": "todo.toggle", "params": {"todo_id": "td_lock"}},
        )
        assert (
            locked_res.is_error is True
            and "409 CLOUD_LOCKED" in locked_res.content
        )


class _EchoProvider:
    async def complete(
        self,
        request: CandidateRequest,
        *,
        attempt: int,
        cancel: asyncio.Event,
    ) -> ModelResponse:
        del attempt, cancel
        text = request.messages[-1].content or ""
        if "LOCK_ERR" in text:
            return ModelResponse(
                content="ERROR: 409 CLOUD_LOCKED on alarm",
                finish_reason=FinishReason.STOP,
            )
        return ModelResponse(
            content=f"completed: {text[:40]}", finish_reason=FinishReason.STOP
        )


@dataclass(frozen=True)
class _PocketTestHarness:
    ledger: NikaLedger
    store: SQLiteEventStore
    client: httpx.AsyncClient
    tx: RecordedFeishuTransport
    adapter: PocketAdapter
    sched: NikaScheduler

    async def close(self) -> None:
        await self.sched.close()
        await self.client.aclose()
        self.store.close()
        await self.ledger.close()


def _make_pocket_harness(
    tmp_path: Path, server: LocalPocketContractServer
) -> _PocketTestHarness:
    init_git_repo(tmp_path / "work", {"a.md": "# A\n"})
    init_git_repo(tmp_path / "personal", {"b.md": "# B\n"})
    ledger = NikaLedger(tmp_path / "nika.db")
    store = SQLiteEventStore(str(tmp_path / "nika.db"))
    client = httpx.AsyncClient(
        transport=server.asgi_transport(), base_url="http://pocket.local"
    )
    tx = RecordedFeishuTransport()
    runtime = NikaToolRuntime()
    register_wiki_tools(
        runtime, WikiMount(tmp_path / "work", tmp_path / "personal")
    )
    register_session_tools(runtime, store, ledger)
    register_workspace_tools(runtime, WorkspaceMount(roots=(tmp_path,)))
    register_feishu_doc_tools(runtime, InMemoryFeishuDocStore())
    register_pocket_tools(
        runtime, PocketRpcClient("http://pocket.local", "pkt_tok", client)
    )
    packs = load_specialist_packs(
        REPO_ROOT / "specialists",
        available_tools=[
            *(s.name for s in runtime.catalog()),
            *ORCHESTRATION_TOOLS,
        ],
        shared_skills_dir=REPO_ROOT / "skills",
    )
    adapter = PocketAdapter(
        PocketAdapterDeps("wh_sec", client, tx, "oc_owner_dm")
    )
    sched = NikaScheduler(
        SchedulerDeps(
            ledger=ledger,
            store=store,
            provider=_EchoProvider(),
            runtime=runtime,
            packs=packs,
            feishu_transport=tx,
            pocket_callback_sender=adapter.deliver_callback,
        )
    )
    adapter.bind_scheduler(sched)
    return _PocketTestHarness(ledger, store, client, tx, adapter, sched)


async def _send_pocket_webhook(
    h: _PocketTestHarness, did: str, cbk: str, prompt: str
) -> bool:
    ok = await h.adapter.handle_webhook(
        "Bearer wh_sec",
        PocketWebhookRequest(
            did,
            f"td_{did}",
            "@nika",
            prompt,
            "2026-11-25T08:00:00Z",
            f"http://pocket.local/v1/deliveries/{did}/result",
            cbk,
        ),
    )
    await h.sched.drain()
    return ok


async def test_pocket_webhook_silent_boundary_and_409_expiry(
    tmp_path: Path,
) -> None:
    server = LocalPocketContractServer(agent_token="pkt_tok")
    server.seed_delivery("del_ok", "cbk_1")
    server.seed_delivery("del_exp", "cbk_2", status="EXPIRED")
    server.seed_delivery("del_alert", "cbk_3")
    h = _make_pocket_harness(tmp_path, server)
    try:
        assert await _send_pocket_webhook(
            h, "del_ok", "cbk_1", "整理今日待办摘要"
        )
        assert server.deliveries["del_ok"]["status"] == "COMPLETED"
        assert len(h.tx.created_cards) == 0

        await _send_pocket_webhook(h, "del_exp", "cbk_2", "整理昨日待办")
        assert len(h.tx.created_cards) == 0

        await _send_pocket_webhook(h, "del_alert", "cbk_3", "LOCK_ERR check")
        assert len(h.tx.created_cards) == 1
    finally:
        await h.close()


async def test_workspace_wiki_deny_macos_alias_and_grep_guards(
    tmp_path: Path,
) -> None:
    wiki_dir = tmp_path / "work_wiki"
    wiki_dir.mkdir()
    (wiki_dir / "note.md").write_text("# Wiki\n")
    outside = tmp_path / "outside_secret.txt"
    outside.write_text("TOP_SECRET_LINE\n")
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "escape_link.txt").symlink_to(outside)

    runtime = NikaToolRuntime()
    register_workspace_tools(
        runtime,
        WorkspaceMount(roots=(tmp_path,), denied_write_roots=(wiki_dir,)),
    )
    denied = await runtime.invoke_direct(
        "write", {"path": str(wiki_dir / "note.md"), "content": "bypass"}
    )
    assert denied.is_error is True
    bad_rx = await runtime.invoke_direct(
        "grep", {"pattern": "[unclosed", "path": str(ws)}
    )
    assert bad_rx.is_error is True
    sym_grep = await runtime.invoke_direct(
        "grep", {"pattern": "TOP_SECRET_.*", "path": str(ws)}
    )
    assert sym_grep.content.startswith("No matches")
    null_bash = await runtime.invoke_direct(
        "bash", {"command": "echo ok", "timeout_seconds": None, "cwd": str(ws)}
    )
    assert null_bash.is_error is False and "ok" in null_bash.content


async def test_macos_tmp_alias_and_feishu_doc_fenced_h2() -> None:
    tmp_alias = Path("/tmp") / f"nika_alias_{os.getpid()}"
    tmp_alias.mkdir(exist_ok=True)
    try:
        rt_alias = NikaToolRuntime()
        register_workspace_tools(rt_alias, WorkspaceMount(roots=(tmp_alias,)))
        alias_w = await rt_alias.invoke_direct(
            "write", {"path": str(tmp_alias / "ok.txt"), "content": "hi"}
        )
        assert alias_w.is_error is False
    finally:
        for child in tmp_alias.glob("*"):
            child.unlink()
        tmp_alias.rmdir()

    fenced_doc = (
        "# Guide\n\n## Setup\n```bash\n## comment inside fence\necho 1\n```\n\n"
        "## Target\nold\n"
    )
    dstore = InMemoryFeishuDocStore({"d_fence": fenced_doc})
    rt = NikaToolRuntime()
    register_feishu_doc_tools(rt, dstore)
    f_res = await rt.invoke_direct(
        "feishu_doc",
        {
            "action": "replace_section",
            "doc_token": "d_fence",
            "heading": "Target",
            "content": "new",
        },
    )
    assert f_res.is_error is False
    after_doc = await dstore.read_doc("d_fence")
    assert "## comment inside fence\necho 1" in after_doc
    assert "## Target\nnew" in after_doc


class _NaturalLockSummaryProvider:
    def __init__(self) -> None:
        self.step = 0

    async def complete(
        self,
        request: CandidateRequest,
        *,
        attempt: int,
        cancel: asyncio.Event,
    ) -> ModelResponse:
        del request, attempt, cancel
        self.step += 1
        if self.step == 1:
            return ModelResponse(
                tool_calls=(
                    ToolCall(
                        "c_lk",
                        "pocket",
                        '{"method":"todo.toggle","params":{"todo_id":"td_lk"}}',
                    ),
                ),
                finish_reason=FinishReason.TOOL_CALLS,
            )
        return ModelResponse(
            content="该闹钟已在手机端上锁，无法远程关闭。",
            finish_reason=FinishReason.STOP,
        )


async def test_pocket_non_json_502_and_structured_lock_escalation(
    tmp_path: Path,
) -> None:
    def _bad_gateway(_req: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html>502 Bad Gateway</html>")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(_bad_gateway),
        base_url="http://pocket.local",
    ) as bad_client:
        rpc = PocketRpcClient("http://pocket.local", "tok", bad_client)
        out = await rpc.call("event.list", {})
        assert isinstance(out, Completed)
        assert out.is_error is True and "502" in out.content

    server = LocalPocketContractServer(agent_token="pkt_tok")
    server.seed_todo("td_lk", "Alarm", locked=True)
    server.seed_delivery("del_nl", "cbk_nl")
    h = _make_pocket_harness(tmp_path, server)
    h.sched.set_provider(_NaturalLockSummaryProvider())
    try:
        await _send_pocket_webhook(h, "del_nl", "cbk_nl", "帮我关掉闹钟")
        assert len(h.tx.created_cards) == 1
    finally:
        await h.close()
