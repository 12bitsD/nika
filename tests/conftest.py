from __future__ import annotations

import asyncio
import multiprocessing
from collections.abc import AsyncIterator

import pytest


@pytest.fixture(autouse=True)
async def _assert_no_leaked_tasks_or_children() -> AsyncIterator[None]:
    before_tasks = {task for task in asyncio.all_tasks() if not task.done()}
    before_children = {proc.pid for proc in multiprocessing.active_children()}
    yield
    await asyncio.sleep(0)
    current = asyncio.current_task()
    leaked_tasks = [
        task
        for task in asyncio.all_tasks()
        if not task.done() and task not in before_tasks and task is not current
    ]
    leaked_children = [
        proc
        for proc in multiprocessing.active_children()
        if proc.pid not in before_children and proc.is_alive()
    ]
    assert not leaked_tasks, f"Leaked background tasks: {leaked_tasks}"
    assert not leaked_children, f"Leaked child processes: {leaked_children}"
