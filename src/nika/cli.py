from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import signal
import sqlite3
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import closing, suppress
from importlib.metadata import version as pkg_version
from pathlib import Path
from typing import Any

import httpx
from nextloop import (
    CandidateRequest,
    Event,
    ModelResponse,
    SQLiteEventStore,
)
from nextloop.events.codec import message_from_data

from .contracts import verify_nextloop_version
from .db import NikaLedger, TaskRecord
from .eval_runner import (
    build_http_client,
    build_openai_provider,
    load_provider_settings,
)
from .feishu import FeishuAdapter, FeishuTransport, RecordedFeishuTransport
from .http_app import HttpDaemonDeps, NikaHttpServer
from .packs import load_specialist_packs
from .pocket import PocketAdapter, PocketAdapterDeps
from .scheduler import ORCHESTRATION_TOOLS, NikaScheduler, SchedulerDeps
from .sessions import register_session_tools
from .tools import NikaToolRuntime

ALL_DECLARED_TOOLS = (
    "wiki",
    "read",
    "write",
    "edit",
    "grep",
    "bash",
    "feishu_doc",
    "pocket",
    "session_ctl",
    *ORCHESTRATION_TOOLS,
)

REDACT_TOKEN_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{12,}"
    r"|(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|gh[pousr]_[A-Za-z0-9_]{16,}"
    r"|github_pat_[A-Za-z0-9_]{16,}"
    r"|xox[baprs]-[A-Za-z0-9-]{12,}"
    r"|AIza[0-9A-Za-z_-]{30,})",
    re.IGNORECASE,
)

REDACT_KV_RE = re.compile(
    r'("(?:token|access_token|refresh_token|callback_token'
    r"|verification_token|encrypt_key|api_key|secret|app_secret"
    r'|client_secret|password)"\s*:\s*")([^"]+)(")',
    re.IGNORECASE,
)


class _NoopRecoveryProvider:
    async def complete(
        self,
        request: CandidateRequest,
        *,
        attempt: int,
        cancel: asyncio.Event,
    ) -> ModelResponse:
        del request, attempt, cancel
        raise RuntimeError("Offline recover does not invoke live LLM turns")


class _FailClosedTransport:
    async def send_card(self, channel_id: str, text: str) -> str:
        del channel_id, text
        raise RuntimeError("Offline recover has no live outbound transport")

    async def patch_card(self, card_id: str, text: str) -> None:
        del card_id, text
        raise RuntimeError("Offline recover has no live outbound transport")

    async def reply_comment(
        self, doc_token: str, comment_id: str, text: str
    ) -> str:
        del doc_token, comment_id, text
        raise RuntimeError("Offline recover has no live outbound transport")


def _redact_secrets(text: str) -> str:
    step1 = REDACT_TOKEN_RE.sub("[REDACTED]", text)
    return REDACT_KV_RE.sub(r"\1[REDACTED]\3", step1)


def _cmd_check(repo_root: Path, db_path: Path) -> int:
    verify_nextloop_version()
    packs = load_specialist_packs(
        repo_root / "specialists",
        available_tools=ALL_DECLARED_TOOLS,
        shared_skills_dir=repo_root / "skills",
    )
    ledger = NikaLedger(db_path)
    asyncio.run(ledger.close())
    print(
        json.dumps(
            {
                "status": "ok",
                "nextloop": pkg_version("nextloop"),
                "specialists": sorted(k.value for k in packs),
                "db": str(db_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _validate_backup_paths(db_path: Path, out_path: Path) -> None:
    if out_path.is_symlink():
        raise PermissionError(f"Refusing symlink backup target: {out_path}")
    if not db_path.is_file():
        raise FileNotFoundError(f"Source DB missing: {db_path}")
    if db_path.resolve() == out_path.resolve():
        raise ValueError(f"Refusing in-place self-backup: {out_path}")


def _cmd_backup(db_path: Path, out_path: Path) -> int:
    _validate_backup_paths(db_path, out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_str = tempfile.mkstemp(
        prefix=".nika-bak-", suffix=".tmp", dir=out_path.parent
    )
    os.close(fd)
    os.chmod(tmp_str, 0o600)
    try:
        with (
            closing(sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)) as s,
            closing(sqlite3.connect(tmp_str)) as dst,
        ):
            s.backup(dst)
            check = dst.execute("PRAGMA integrity_check").fetchone()
        if not (check and check[0] == "ok") or out_path.is_symlink():
            raise RuntimeError(f"Backup verification failed: {check}")
        os.replace(tmp_str, out_path)
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp_str)
        raise
    print(json.dumps({"status": "ok", "backup": str(out_path)}))
    return 0


def _event_to_export_msg(ev: Event) -> dict[str, Any] | None:
    raw_msg = ev.payload.get("message")
    if not isinstance(raw_msg, Mapping):
        return None
    msg = message_from_data(raw_msg)
    body = _redact_secrets(msg.content or "")
    return {"role": msg.role, "content": body}


async def _export_task_row(
    store: SQLiteEventStore, task: TaskRecord
) -> dict[str, Any]:
    events = await store.load_surface(task.session_id)
    msgs = [
        m for m in (_event_to_export_msg(ev) for ev in events) if m is not None
    ]
    return {
        "task_id": task.task_id,
        "session_id": task.session_id,
        "specialist": task.specialist.value,
        "status": task.status.value,
        "report_status": task.report_status.value if task.report_status else "",
        "messages": msgs,
    }


def _write_single_jsonl(
    out_dir: Path, spec: str, lines: list[str]
) -> tuple[str, int]:
    target = out_dir / f"{spec}.jsonl"
    if target.is_symlink():
        raise PermissionError(f"Refusing symlink export target: {target}")
    fd, tmp_str = tempfile.mkstemp(
        prefix=f".{spec}-", suffix=".tmp", dir=out_dir
    )
    os.close(fd)
    os.chmod(tmp_str, 0o600)
    try:
        Path(tmp_str).write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp_str, target)
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp_str)
        raise
    return spec, len(lines)


def _write_grouped_jsonl(
    out_dir: Path, rows: Sequence[dict[str, Any]]
) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    grouped: dict[str, list[str]] = {}
    for row in rows:
        grouped.setdefault(str(row["specialist"]), []).append(
            json.dumps(row, ensure_ascii=False)
        )
    return dict(
        _write_single_jsonl(out_dir, s, lns) for s, lns in grouped.items()
    )


async def _export_async(db_path: Path, out_dir: Path) -> dict[str, int]:
    ledger = NikaLedger(db_path)
    store = SQLiteEventStore(str(db_path))
    try:
        tasks = await ledger.list_settled_tasks()
        rows = [await _export_task_row(store, t) for t in tasks]
    finally:
        store.close()
        await ledger.close()
    return await asyncio.to_thread(_write_grouped_jsonl, out_dir, rows)


async def _recover_offline_async(
    repo_root: Path, db_path: Path
) -> dict[str, int]:
    ledger = NikaLedger(db_path)
    store = SQLiteEventStore(str(db_path))
    packs = load_specialist_packs(
        repo_root / "specialists",
        available_tools=ALL_DECLARED_TOOLS,
        shared_skills_dir=repo_root / "skills",
    )
    tx: FeishuTransport = _FailClosedTransport()
    sched = NikaScheduler(
        SchedulerDeps(
            ledger=ledger,
            store=store,
            provider=_NoopRecoveryProvider(),
            runtime=NikaToolRuntime(),
            packs=packs,
            feishu_transport=tx,
        )
    )
    try:
        rep = await sched.recover_offline()
        await sched.close()
    finally:
        store.close()
        await ledger.close()
    return {
        "redelivered": rep.redelivered,
        "failed_interrupted": rep.failed_interrupted,
        "resumed_queued": rep.resumed_queued,
    }


def _build_optional_pocket(
    env: Mapping[str, str],
    http_client: httpx.AsyncClient,
    tx: FeishuTransport,
) -> PocketAdapter | None:
    secret = env.get("NIKA_POCKET_WEBHOOK_SECRET", "").strip()
    if not secret:
        return None
    return PocketAdapter(
        PocketAdapterDeps(
            webhook_secret=secret,
            http_client=http_client,
            feishu_transport=tx,
            owner_dm_channel=env.get("NIKA_OWNER_DM_CHANNEL", ""),
            allowed_callback_origin=env.get("NIKA_POCKET_CALLBACK_ORIGIN", ""),
        )
    )


def _build_serve_http(
    sched: NikaScheduler,
    pocket_adapter: PocketAdapter | None,
    env: Mapping[str, str],
) -> NikaHttpServer:
    if pocket_adapter is not None:
        pocket_adapter.bind_scheduler(sched)
    raw_allow = env.get("NIKA_FEISHU_ALLOWLIST", "")
    allow = frozenset(x.strip() for x in raw_allow.split(",") if x.strip())
    return NikaHttpServer(
        HttpDaemonDeps(
            feishu_adapter=FeishuAdapter(scheduler=sched, allowlist=allow),
            pocket_adapter=pocket_adapter,
            feishu_verification_token=env.get("NIKA_FEISHU_VERIFY_TOKEN", ""),
            feishu_encrypt_key=env.get("NIKA_FEISHU_ENCRYPT_KEY", ""),
        )
    )


async def _wait_stop_signal() -> None:
    stop_ev = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_ev.set)
    await stop_ev.wait()


async def _serve_with_provider(
    ns: argparse.Namespace,
    paths: tuple[Path, Path],
    env: Mapping[str, str],
    clients: tuple[Any, httpx.AsyncClient],
) -> int:
    ledger = NikaLedger(paths[1])
    store = SQLiteEventStore(str(paths[1]))
    runtime = NikaToolRuntime()
    register_session_tools(runtime, store, ledger)
    tx = RecordedFeishuTransport()
    p_adapter = _build_optional_pocket(env, clients[1], tx)
    packs = load_specialist_packs(
        paths[0] / "specialists",
        available_tools=ALL_DECLARED_TOOLS,
        shared_skills_dir=paths[0] / "skills",
    )
    sched = NikaScheduler(
        SchedulerDeps(
            ledger=ledger,
            store=store,
            provider=clients[0],
            runtime=runtime,
            packs=packs,
            feishu_transport=tx,
            shared_skills_dir=paths[0] / "skills",
            pocket_callback_sender=(
                p_adapter.deliver_callback if p_adapter else None
            ),
        )
    )
    server = _build_serve_http(sched, p_adapter, env)
    try:
        await sched.recover()
        bound = await server.start(ns.host, int(ns.port))
        print(json.dumps({"status": "serving", "port": bound}), flush=True)
        await _wait_stop_signal()
    finally:
        await server.close()
        await sched.close()
        store.close()
        await ledger.close()
    return 0


async def _serve_async(
    ns: argparse.Namespace,
    paths: tuple[Path, Path, Path],
    env: Mapping[str, str],
) -> int:
    repo, db_path, cfg_path = paths
    settings = load_provider_settings(env, cfg_path)
    async with (
        build_http_client(settings) as p_http,
        httpx.AsyncClient(timeout=15.0) as cb_http,
    ):
        provider = build_openai_provider(settings, p_http)
        return await _serve_with_provider(
            ns, (repo, db_path), env, (provider, cb_http)
        )


def _build_parser(env: Mapping[str, str]) -> argparse.ArgumentParser:
    default_repo = str(Path(__file__).resolve().parents[2])
    default_db = env.get("NIKA_DB_PATH", ".local/nika.db")
    parser = argparse.ArgumentParser(prog="nika")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_chk = sub.add_parser("check")
    p_chk.add_argument("--repo-root", default=default_repo)
    p_chk.add_argument("--db", default=default_db)

    p_bak = sub.add_parser("backup")
    p_bak.add_argument("--db", required=True)
    p_bak.add_argument("--out", required=True)

    p_exp = sub.add_parser("export")
    p_exp.add_argument("--db", required=True)
    p_exp.add_argument("--out", required=True)

    p_rec = sub.add_parser("recover")
    p_rec.add_argument("--repo-root", default=default_repo)
    p_rec.add_argument("--db", required=True)

    p_srv = sub.add_parser("serve")
    p_srv.add_argument("--repo-root", default=default_repo)
    p_srv.add_argument("--db", default=default_db)
    p_srv.add_argument("--host", default="127.0.0.1")
    p_srv.add_argument("--port", type=int, default=8787)
    return parser


def run_cli(
    argv: Sequence[str] | None = None,
    env_override: Mapping[str, str] | None = None,
) -> int:
    # bits:allow(BCS011): CLI entrypoint reads process environment
    env = dict(os.environ) if env_override is None else dict(env_override)
    ns = _build_parser(env).parse_args(list(argv) if argv is not None else None)
    if ns.cmd == "check":
        return _cmd_check(Path(ns.repo_root), Path(ns.db))
    if ns.cmd == "backup":
        return _cmd_backup(Path(ns.db), Path(ns.out))
    if ns.cmd == "export":
        counts = asyncio.run(_export_async(Path(ns.db), Path(ns.out)))
        print(json.dumps({"status": "ok", "exported": counts}))
        return 0
    if ns.cmd == "recover":
        summary = asyncio.run(
            _recover_offline_async(Path(ns.repo_root), Path(ns.db))
        )
        print(json.dumps({"status": "ok", "recovery": summary}))
        return 0
    repo = Path(ns.repo_root).resolve()
    db_path = Path(ns.db).resolve()
    cfg_path = Path(
        env.get(
            "NIKA_PROVIDER_CONFIG", str(repo / ".local" / "eval_provider.json")
        )
    )
    return asyncio.run(_serve_async(ns, (repo, db_path, cfg_path), env))


def main() -> None:
    raise SystemExit(run_cli())
