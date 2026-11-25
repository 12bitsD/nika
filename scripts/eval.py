#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import os
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from nextloop import (
    AgentLoop,
    InMemoryEventStore,
    LoopConfig,
    MemoryDeliveryOwner,
    ModelProvider,
    ToolContext,
    ToolEffect,
    ToolExecutionMode,
    ToolRegistry,
    ToolSpec,
    TurnContext,
    TurnStatus,
)

from nika.eval_runner import (
    EvalCaseResult,
    EvalOutcomeKind,
    JudgeInput,
    build_http_client,
    build_openai_provider,
    judge_delivery,
    load_provider_settings,
    run_case_with_retry,
)
from nika.eval_suites_s1 import run_stage1_evals
from nika.eval_suites_s2 import run_stage2_evals
from nika.eval_suites_s3 import run_stage3_evals


def _build_probe_registry(
    expected_nonce: str, called_args: list[str]
) -> ToolRegistry:
    registry = ToolRegistry()

    def _probe(args: Mapping[str, Any], _ctx: ToolContext) -> str:
        called_args.append(str(args["key"]))
        return f"probe_token={expected_nonce}"

    registry.register(
        ToolSpec(
            name="probe_echo",
            description="Fetch live probe token for the requested key.",
            parameters={
                "type": "object",
                "properties": {"key": {"type": "string"}},
                "required": ["key"],
                "additionalProperties": False,
            },
            mode=ToolExecutionMode.PARALLEL,
            effect=ToolEffect.READ_ONLY,
        ),
        _probe,
    )
    return registry


async def _case_f0_live_tool_and_judge(
    provider: ModelProvider,
) -> tuple[bool, str]:
    expected_nonce = f"NONCE-{uuid.uuid4().hex[:8]}"
    called_args: list[str] = []
    registry = _build_probe_registry(expected_nonce, called_args)
    delivery = MemoryDeliveryOwner()
    prompt = (
        "调 probe_echo 查 key='alpha'，直接把返回的 token 告诉我，不加客套话。"
    )
    sys_prompt = (
        "结论先行，一句话直接给工具返回的真实结果，不加寒暄或步骤说明。"
    )
    outcome = await AgentLoop().run(
        TurnContext(
            session_id="eval_f0_1",
            initial_input=prompt,
            config=LoopConfig(system_prompt=sys_prompt),
            store=InMemoryEventStore(),
            provider=provider,
            tools=registry,
            delivery=delivery,
        )
    )
    if outcome.status != TurnStatus.SUCCEEDED or not delivery.messages:
        return False, f"turn status={outcome.status}"
    reply = delivery.messages[-1].content.strip()
    if called_args != ["alpha"] or expected_nonce not in reply:
        return False, f"calls={called_args} reply={reply!r}"
    verdict = await judge_delivery(
        provider,
        JudgeInput(
            query="查 key='alpha' 的 probe_token",
            evidence=f"probe_echo('alpha') -> probe_token={expected_nonce}",
            delivered_text=reply,
        ),
    )
    return verdict.passed, f"reply={reply!r} judge={verdict.reason}"


async def _case_f0_judge_rejects_hallucination(
    provider: ModelProvider,
) -> tuple[bool, str]:
    verdict = await judge_delivery(
        provider,
        JudgeInput(
            query="把结论写入 Wiki",
            evidence="No tool was called; zero Git commits created.",
            delivered_text="已成功写入 Wiki，提交记录 rev 9f8e7d6。",
        ),
    )
    rejected = not verdict.passed
    return rejected, f"negative_control_rejected={rejected} ({verdict.reason})"


async def _run_suite(stage: int, env: Mapping[str, str], repo: Path) -> int:
    cfg_path = repo / ".local" / "eval_provider.json"
    settings = load_provider_settings(env, cfg_path)
    results: list[EvalCaseResult] = []
    async with build_http_client(settings) as client:
        provider = build_openai_provider(settings, client)
        if stage >= 0:
            results.append(
                await run_case_with_retry(
                    "F0",
                    "F0.1_live_tool_and_judge",
                    lambda: _case_f0_live_tool_and_judge(provider),
                )
            )
            results.append(
                await run_case_with_retry(
                    "F0",
                    "F0.2_judge_rejects_hallucination",
                    lambda: _case_f0_judge_rejects_hallucination(provider),
                )
            )
        if stage >= 1:
            results.extend(await run_stage1_evals(provider, repo))
        if stage >= 2:
            results.extend(await run_stage2_evals(provider, repo))
        if stage >= 3:
            results.extend(await run_stage3_evals(provider, repo))
    if any(r.outcome == EvalOutcomeKind.INFRA_ERROR for r in results):
        return 2
    if any(r.outcome != EvalOutcomeKind.PASSED for r in results):
        return 1
    print(
        f"EVAL_STAGE_{stage}_ALL_PASSED ({len(results)}/{len(results)})",
        flush=True,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Nika live kimi-k3.1-pro Eval")
    parser.add_argument("--stage", type=int, default=0)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parent.parent
    # bits:allow(BCS011): CLI entrypoint reads process environment
    env = dict(os.environ)
    return asyncio.run(_run_suite(args.stage, env, repo))


if __name__ == "__main__":
    raise SystemExit(main())
