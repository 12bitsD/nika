from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from nextloop import new_id, utc_now

from .contracts import (
    IngressEnvelope,
    IngressSource,
    ReplyKind,
    ReplyTarget,
    ReportStatus,
    SpecialistId,
    TaskKind,
    TaskStatus,
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS ingress_events (
    event_id    TEXT PRIMARY KEY,
    source      TEXT NOT NULL CHECK (source IN ('feishu', 'pocket')),
    thread_key  TEXT NOT NULL,
    task_id     TEXT NOT NULL,
    received_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    task_id           TEXT PRIMARY KEY,
    session_id        TEXT NOT NULL UNIQUE,
    parent_task_id    TEXT,
    origin_event_id   TEXT,
    origin_call_id    TEXT,
    thread_key        TEXT NOT NULL,
    kind              TEXT NOT NULL
                      CHECK (kind IN ('ingress', 'dispatch', 'consult')),
    specialist        TEXT NOT NULL CHECK (
                      specialist IN (
                          'main', 'top_talent', 'coder', 'doc_research', 'eval'
                      )),
    depth             INTEGER NOT NULL CHECK (depth IN (0, 1)),
    status            TEXT NOT NULL CHECK (
                      status IN (
                          'queued', 'running', 'need_decision',
                          'blocked', 'done', 'failed'
                      )),
    report_status     TEXT CHECK (
                      report_status IS NULL OR report_status IN (
                          'done', 'need_decision', 'blocked',
                          'handoff', 'dispatched'
                      )),
    prompt            TEXT NOT NULL,
    reply_target_json TEXT,
    summary           TEXT,
    final_message_id  TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS tasks_consult_call_idx
    ON tasks(parent_task_id, origin_call_id) WHERE kind = 'consult';

CREATE TABLE IF NOT EXISTS threads (
    thread_key      TEXT PRIMARY KEY,
    active_task_id  TEXT UNIQUE,
    last_session_id TEXT,
    last_specialist TEXT,
    last_task_id    TEXT,
    updated_at      TEXT NOT NULL
);
"""


class IngressAction(StrEnum):
    START_NEW = "start_new"
    DUPLICATE = "duplicate"
    STEER_ACTIVE = "steer_active"
    RESUME_DECISION = "resume_decision"
    HOLD_BLOCKED = "hold_blocked"


@dataclass(frozen=True)
class TaskRecord:
    task_id: str
    session_id: str
    parent_task_id: str | None
    origin_event_id: str | None
    origin_call_id: str | None
    thread_key: str
    kind: TaskKind
    specialist: SpecialistId
    depth: int
    status: TaskStatus
    report_status: ReportStatus | None
    prompt: str
    reply_target: ReplyTarget | None
    summary: str | None
    final_message_id: str | None
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class IngressDecision:
    action: IngressAction
    task: TaskRecord | None


@dataclass(frozen=True)
class ChildTaskSpec:
    parent_task_id: str
    origin_event_id: str | None
    origin_call_id: str
    thread_key: str
    kind: TaskKind
    specialist: SpecialistId
    depth: int
    prompt: str
    reply_target: ReplyTarget | None = None


def _encode_target(target: ReplyTarget | None) -> str | None:
    if target is None:
        return None
    return json.dumps(
        {
            "kind": target.kind.value,
            "channel_id": target.channel_id,
            "callback_url": target.callback_url,
            "callback_token": target.callback_token,
            "notify_channel_id": target.notify_channel_id,
            "metadata": dict(target.metadata),
        },
        ensure_ascii=False,
    )


def _decode_target(raw: str | None) -> ReplyTarget | None:
    if not raw:
        return None
    data: dict[str, Any] = json.loads(raw)
    return ReplyTarget(
        kind=ReplyKind(data["kind"]),
        channel_id=str(data.get("channel_id", "")),
        callback_url=str(data.get("callback_url", "")),
        callback_token=str(data.get("callback_token", "")),
        notify_channel_id=str(data.get("notify_channel_id", "")),
        metadata=dict(data.get("metadata") or {}),
    )


def _row_to_task(row: sqlite3.Row) -> TaskRecord:
    rep = row["report_status"]
    return TaskRecord(
        task_id=str(row["task_id"]),
        session_id=str(row["session_id"]),
        parent_task_id=row["parent_task_id"],
        origin_event_id=row["origin_event_id"],
        origin_call_id=row["origin_call_id"],
        thread_key=str(row["thread_key"]),
        kind=TaskKind(row["kind"]),
        specialist=SpecialistId(row["specialist"]),
        depth=int(row["depth"]),
        status=TaskStatus(row["status"]),
        report_status=ReportStatus(rep) if rep is not None else None,
        prompt=str(row["prompt"]),
        reply_target=_decode_target(row["reply_target_json"]),
        summary=row["summary"],
        final_message_id=row["final_message_id"],
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


class NikaLedger:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(self.path), check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.execute("PRAGMA busy_timeout=5000")
            self._conn.executescript(SCHEMA_SQL)

    @contextmanager
    def _write_tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                self._conn.execute("COMMIT")
            except BaseException:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise

    async def close(self) -> None:
        await asyncio.to_thread(self._close_sync)

    def _close_sync(self) -> None:
        with self._lock:
            self._conn.close()

    async def accept_ingress(
        self, envelope: IngressEnvelope
    ) -> IngressDecision:
        return await asyncio.to_thread(self._accept_ingress_sync, envelope)

    def _accept_ingress_sync(
        self, envelope: IngressEnvelope
    ) -> IngressDecision:
        now = utc_now()
        with self._write_tx() as conn:
            existing = conn.execute(
                "SELECT task_id FROM ingress_events WHERE event_id = ?",
                (envelope.event_id,),
            ).fetchone()
            if existing is not None:
                task = self._get_task_locked(str(existing["task_id"]))
                return IngressDecision(IngressAction.DUPLICATE, task)
            t_row = conn.execute(
                "SELECT * FROM threads WHERE thread_key = ?",
                (envelope.thread_key,),
            ).fetchone()
            active_id = t_row["active_task_id"] if t_row is not None else None
            if active_id is not None:
                return self._route_active_locked(envelope, str(active_id), now)
            specialist = SpecialistId.MAIN
            if (
                t_row is not None
                and t_row["last_specialist"]
                and envelope.source == IngressSource.FEISHU
            ):
                specialist = SpecialistId(t_row["last_specialist"])
            created = self._insert_ingress_task_locked(
                envelope, specialist, now
            )
            return IngressDecision(IngressAction.START_NEW, created)

    def _route_active_locked(
        self,
        envelope: IngressEnvelope,
        active_id: str,
        now: str,
    ) -> IngressDecision:
        active = self._require_task_locked(active_id)
        self._conn.execute(
            "INSERT INTO ingress_events(event_id, source, thread_key, task_id, received_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                envelope.event_id,
                envelope.source.value,
                envelope.thread_key,
                active.task_id,
                now,
            ),
        )
        if active.status in (TaskStatus.QUEUED, TaskStatus.RUNNING):
            return IngressDecision(IngressAction.STEER_ACTIVE, active)
        if active.status == TaskStatus.NEED_DECISION:
            self._conn.execute(
                "UPDATE tasks SET status = ?, report_status = NULL, "
                "updated_at = ? WHERE task_id = ?",
                (TaskStatus.QUEUED.value, now, active.task_id),
            )
            updated = self._require_task_locked(active.task_id)
            return IngressDecision(IngressAction.RESUME_DECISION, updated)
        return IngressDecision(IngressAction.HOLD_BLOCKED, active)

    def _insert_ingress_task_locked(
        self,
        envelope: IngressEnvelope,
        specialist: SpecialistId,
        now: str,
    ) -> TaskRecord:
        task_id = new_id("task")
        session_id = new_id("sess")
        self._conn.execute(
            "INSERT INTO tasks(task_id, session_id, parent_task_id, origin_event_id, "
            "origin_call_id, thread_key, kind, specialist, depth, status, report_status, "
            "prompt, reply_target_json, summary, final_message_id, created_at, updated_at) "
            "VALUES (?, ?, NULL, ?, NULL, ?, ?, ?, 0, ?, NULL, ?, ?, NULL, NULL, ?, ?)",
            (
                task_id,
                session_id,
                envelope.event_id,
                envelope.thread_key,
                TaskKind.INGRESS.value,
                specialist.value,
                TaskStatus.QUEUED.value,
                envelope.prompt,
                _encode_target(envelope.reply_target),
                now,
                now,
            ),
        )
        self._conn.execute(
            "INSERT INTO ingress_events(event_id, source, thread_key, task_id, received_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                envelope.event_id,
                envelope.source.value,
                envelope.thread_key,
                task_id,
                now,
            ),
        )
        self._conn.execute(
            "INSERT INTO threads(thread_key, active_task_id, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(thread_key) DO UPDATE SET active_task_id = excluded.active_task_id, "
            "updated_at = excluded.updated_at",
            (envelope.thread_key, task_id, now),
        )
        return self._require_task_locked(task_id)

    async def create_child_task(self, spec: ChildTaskSpec) -> TaskRecord:
        return await asyncio.to_thread(self._create_child_sync, spec)

    def _create_child_sync(self, spec: ChildTaskSpec) -> TaskRecord:
        now = utc_now()
        with self._write_tx() as conn:
            if spec.kind == TaskKind.CONSULT:
                found = conn.execute(
                    "SELECT * FROM tasks WHERE parent_task_id = ? AND origin_call_id = ? "
                    "AND kind = 'consult'",
                    (spec.parent_task_id, spec.origin_call_id),
                ).fetchone()
                if found is not None:
                    return _row_to_task(found)
            task_id = new_id("task")
            session_id = new_id("sess")
            ev_id = spec.origin_event_id or spec.parent_task_id
            conn.execute(
                "INSERT INTO tasks(task_id, session_id, parent_task_id, origin_event_id, "
                "origin_call_id, thread_key, kind, specialist, depth, status, report_status, "
                "prompt, reply_target_json, summary, final_message_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, NULL, NULL, ?, ?)",
                (
                    task_id,
                    session_id,
                    spec.parent_task_id,
                    ev_id,
                    spec.origin_call_id,
                    spec.thread_key,
                    spec.kind.value,
                    spec.specialist.value,
                    spec.depth,
                    TaskStatus.QUEUED.value,
                    spec.prompt,
                    _encode_target(spec.reply_target),
                    now,
                    now,
                ),
            )
            if spec.kind == TaskKind.DISPATCH:
                conn.execute(
                    "INSERT INTO threads(thread_key, active_task_id, updated_at) "
                    "VALUES (?, ?, ?) ON CONFLICT(thread_key) DO UPDATE SET "
                    "active_task_id = excluded.active_task_id, updated_at = excluded.updated_at",
                    (spec.thread_key, task_id, now),
                )
            return self._require_task_locked(task_id)

    async def set_task_status(self, task_id: str, status: TaskStatus) -> None:
        await asyncio.to_thread(self._set_status_sync, task_id, status)

    def _set_status_sync(self, task_id: str, status: TaskStatus) -> None:
        now = utc_now()
        with self._write_tx() as conn:
            conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE task_id = ?",
                (status.value, now, task_id),
            )
            if status in (TaskStatus.DONE, TaskStatus.FAILED):
                conn.execute(
                    "UPDATE threads SET active_task_id = NULL, updated_at = ? "
                    "WHERE active_task_id = ?",
                    (now, task_id),
                )

    async def record_report(
        self, task_id: str, status: ReportStatus, summary: str
    ) -> None:
        await asyncio.to_thread(
            self._record_report_sync, task_id, status, summary
        )

    def _record_report_sync(
        self, task_id: str, status: ReportStatus, summary: str
    ) -> None:
        with self._write_tx() as conn:
            conn.execute(
                "UPDATE tasks SET report_status = ?, summary = ?, updated_at = ? "
                "WHERE task_id = ?",
                (status.value, summary, utc_now(), task_id),
            )

    async def settle_delivered(
        self, task_id: str, final_message_id: str, content: str
    ) -> TaskRecord:
        return await asyncio.to_thread(
            self._settle_delivered_sync, task_id, final_message_id, content
        )

    async def cancel_task_if_open(self, task_id: str) -> bool:
        return await asyncio.to_thread(self._cancel_open_sync, task_id)

    def _cancel_open_sync(self, task_id: str) -> bool:
        now = utc_now()
        with self._write_tx() as conn:
            cur = conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? "
                "WHERE (task_id = ? OR parent_task_id = ?) "
                "AND status IN (?, ?, ?, ?)",
                (
                    TaskStatus.FAILED.value,
                    now,
                    task_id,
                    task_id,
                    TaskStatus.QUEUED.value,
                    TaskStatus.RUNNING.value,
                    TaskStatus.NEED_DECISION.value,
                    TaskStatus.BLOCKED.value,
                ),
            )
            conn.execute(
                "UPDATE threads SET active_task_id = NULL, updated_at = ? "
                "WHERE active_task_id = ?",
                (now, task_id),
            )
            return cur.rowcount > 0

    def _insert_handoff_child_locked(self, task: TaskRecord, now: str) -> str:
        call_id = f"handoff_{task.task_id}"
        found = self._conn.execute(
            "SELECT task_id FROM tasks WHERE parent_task_id = ? "
            "AND origin_call_id = ?",
            (task.task_id, call_id),
        ).fetchone()
        if found is not None:
            return str(found["task_id"])
        cid = new_id("task")
        sid = new_id("sess")
        ev_id = task.origin_event_id or task.task_id
        ho_prompt = (
            f"{task.prompt}\n\n"
            f"[Handoff from {task.specialist.value}: {task.summary}]"
        )
        self._conn.execute(
            "INSERT INTO tasks(task_id, session_id, parent_task_id, origin_event_id, "
            "origin_call_id, thread_key, kind, specialist, depth, status, report_status, "
            "prompt, reply_target_json, summary, final_message_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, NULL, ?, ?, NULL, NULL, ?, ?)",
            (
                cid,
                sid,
                task.task_id,
                ev_id,
                call_id,
                task.thread_key,
                TaskKind.DISPATCH.value,
                SpecialistId.MAIN.value,
                TaskStatus.QUEUED.value,
                ho_prompt,
                _encode_target(task.reply_target),
                now,
                now,
            ),
        )
        return cid

    def _settle_delivered_sync(
        self, task_id: str, final_message_id: str, content: str
    ) -> TaskRecord:
        now = utc_now()
        with self._write_tx() as conn:
            task = self._require_task_locked(task_id)
            rep = task.report_status
            summary = content or task.summary
            next_status = TaskStatus.DONE
            if rep == ReportStatus.NEED_DECISION:
                next_status = TaskStatus.NEED_DECISION
            elif rep == ReportStatus.BLOCKED:
                next_status = TaskStatus.BLOCKED
            conn.execute(
                "UPDATE tasks SET status = ?, summary = ?, final_message_id = ?, "
                "updated_at = ? WHERE task_id = ?",
                (next_status.value, summary, final_message_id, now, task_id),
            )
            self._update_thread_on_settle_locked(task, next_status, now)
            return self._require_task_locked(task_id)

    def _update_thread_on_settle_locked(
        self,
        task: TaskRecord,
        next_status: TaskStatus,
        now: str,
    ) -> None:
        if task.kind == TaskKind.CONSULT:
            return
        if (
            next_status == TaskStatus.FAILED
            or task.report_status == ReportStatus.DISPATCHED
        ):
            self._conn.execute(
                "UPDATE threads SET active_task_id = NULL, updated_at = ? "
                "WHERE thread_key = ? AND active_task_id = ?",
                (now, task.thread_key, task.task_id),
            )
            return
        if next_status != TaskStatus.DONE:
            return
        if task.report_status == ReportStatus.HANDOFF:
            if task.specialist != SpecialistId.MAIN:
                cid = self._insert_handoff_child_locked(task, now)
                self._conn.execute(
                    "UPDATE threads SET active_task_id = ?, last_specialist = NULL, "
                    "updated_at = ? WHERE thread_key = ?",
                    (cid, now, task.thread_key),
                )
            return
        keep_spec = (
            task.specialist.value
            if task.specialist != SpecialistId.MAIN
            else None
        )
        self._conn.execute(
            "UPDATE threads SET active_task_id = NULL, last_session_id = ?, "
            "last_specialist = ?, last_task_id = ?, updated_at = ? "
            "WHERE thread_key = ? AND active_task_id = ?",
            (
                task.session_id,
                keep_spec,
                task.task_id,
                now,
                task.thread_key,
                task.task_id,
            ),
        )

    def _require_task_locked(self, task_id: str) -> TaskRecord:
        found = self._get_task_locked(task_id)
        if found is None:
            raise LookupError(f"Task not found: {task_id}")
        return found

    def _get_task_locked(self, task_id: str) -> TaskRecord | None:
        row = self._conn.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        return _row_to_task(row) if row is not None else None

    async def get_task(self, task_id: str) -> TaskRecord | None:
        return await asyncio.to_thread(self._get_task_sync, task_id)

    def _get_task_sync(self, task_id: str) -> TaskRecord | None:
        with self._lock:
            return self._get_task_locked(task_id)

    async def get_task_by_session(self, session_id: str) -> TaskRecord | None:
        return await asyncio.to_thread(self._get_by_session_sync, session_id)

    def _get_by_session_sync(self, session_id: str) -> TaskRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM tasks WHERE session_id = ?", (session_id,)
            ).fetchone()
            return _row_to_task(row) if row is not None else None

    async def get_active_task(self, thread_key: str) -> TaskRecord | None:
        return await asyncio.to_thread(self._get_active_sync, thread_key)

    def _get_active_sync(self, thread_key: str) -> TaskRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT active_task_id FROM threads WHERE thread_key = ?",
                (thread_key,),
            ).fetchone()
            if row is None or row["active_task_id"] is None:
                return None
            return self._get_task_locked(str(row["active_task_id"]))

    async def get_thread_last_session(self, thread_key: str) -> str | None:
        return await asyncio.to_thread(self._get_last_sess_sync, thread_key)

    def _get_last_sess_sync(self, thread_key: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT last_session_id FROM threads WHERE thread_key = ?",
                (thread_key,),
            ).fetchone()
            return (
                str(row["last_session_id"])
                if row and row["last_session_id"]
                else None
            )

    async def list_tasks_for_thread(
        self, thread_key: str
    ) -> tuple[TaskRecord, ...]:
        return await asyncio.to_thread(self._list_for_thread_sync, thread_key)

    def _list_for_thread_sync(self, thread_key: str) -> tuple[TaskRecord, ...]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE thread_key = ? ORDER BY created_at ASC",
                (thread_key,),
            ).fetchall()
            return tuple(_row_to_task(r) for r in rows)

    async def count_handoffs(self, origin_event_id: str) -> int:
        return await asyncio.to_thread(
            self._count_handoffs_sync, origin_event_id
        )

    def _count_handoffs_sync(self, origin_event_id: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS cnt FROM tasks "
                "WHERE (origin_event_id = ? OR task_id = ?) "
                "AND report_status = 'handoff'",
                (origin_event_id, origin_event_id),
            ).fetchone()
            return int(row["cnt"]) if row is not None else 0

    async def get_handoff_child(self, parent_task_id: str) -> TaskRecord | None:
        return await asyncio.to_thread(
            self._get_handoff_child_sync, parent_task_id
        )

    def _get_handoff_child_sync(self, parent_task_id: str) -> TaskRecord | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM tasks WHERE parent_task_id = ? "
                "AND origin_call_id = ?",
                (parent_task_id, f"handoff_{parent_task_id}"),
            ).fetchone()
            return _row_to_task(row) if row is not None else None

    async def list_open_children(
        self, parent_task_id: str
    ) -> tuple[TaskRecord, ...]:
        return await asyncio.to_thread(
            self._list_open_children_sync, parent_task_id
        )

    def _list_open_children_sync(
        self, parent_task_id: str
    ) -> tuple[TaskRecord, ...]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM tasks WHERE parent_task_id = ? "
                "AND status IN ('queued', 'running')",
                (parent_task_id,),
            ).fetchall()
            return tuple(_row_to_task(r) for r in rows)
