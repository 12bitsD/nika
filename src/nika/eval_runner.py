from __future__ import annotations

import asyncio
import json
import ssl
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx
from nextloop import (
    CandidateRequest,
    Message,
    ModelProvider,
    OpenAIProvider,
    ProviderError,
)

DEFAULT_EVAL_MODEL = "kimi-k3.1-pro"
DEFAULT_EVAL_TIMEOUT = 90.0


class EvalOutcomeKind(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    INFRA_ERROR = "infra_error"


@dataclass(frozen=True)
class JudgeVerdict:
    passed: bool
    reason: str


@dataclass(frozen=True)
class JudgeInput:
    query: str
    evidence: str
    delivered_text: str
    rubric: str = ""


@dataclass(frozen=True)
class EvalCaseResult:
    feature: str
    case_id: str
    outcome: EvalOutcomeKind
    detail: str


@dataclass(frozen=True)
class LiveProviderSettings:
    base_url: str
    api_key: str = field(repr=False)
    model_id: str = DEFAULT_EVAL_MODEL
    ca_bundle: str = ""

    def __post_init__(self) -> None:
        if not self.base_url.strip() or not self.api_key.strip():
            raise ValueError("base_url and api_key must be non-empty")


def load_provider_settings(
    env: Mapping[str, str], local_file: Path
) -> LiveProviderSettings:
    env_url = env.get("NIKA_EVAL_BASE_URL", "").strip()
    env_key = env.get("NIKA_EVAL_API_KEY", "").strip()
    if bool(env_url) != bool(env_key):
        raise ValueError(
            "partial NIKA_EVAL_* config: set both BASE_URL and API_KEY"
        )
    if env_url and env_key:
        return LiveProviderSettings(
            base_url=env_url,
            api_key=env_key,
            model_id=env.get("NIKA_EVAL_MODEL", DEFAULT_EVAL_MODEL).strip()
            or DEFAULT_EVAL_MODEL,
            ca_bundle=env.get("SSL_CERT_FILE", "").strip(),
        )
    if not local_file.is_file():
        raise RuntimeError(
            f"Missing eval config at {local_file} and NIKA_EVAL_* env vars"
        )
    raw = json.loads(local_file.read_text(encoding="utf-8"))
    return LiveProviderSettings(
        base_url=str(raw["base_url"]),
        api_key=str(raw["api_key"]),
        model_id=str(raw.get("model_id", DEFAULT_EVAL_MODEL)),
        ca_bundle=str(raw.get("ca_bundle", "")),
    )


def build_http_client(settings: LiveProviderSettings) -> httpx.AsyncClient:
    if settings.ca_bundle.strip():
        bundle = Path(settings.ca_bundle)
        if not bundle.is_file():
            raise FileNotFoundError(f"ca_bundle not found: {bundle}")
        ctx = ssl.create_default_context(cafile=str(bundle))
        return httpx.AsyncClient(verify=ctx, timeout=DEFAULT_EVAL_TIMEOUT)
    return httpx.AsyncClient(timeout=DEFAULT_EVAL_TIMEOUT)


def build_openai_provider(
    settings: LiveProviderSettings, client: httpx.AsyncClient
) -> OpenAIProvider:
    return OpenAIProvider(
        model_id=settings.model_id,
        base_url=settings.base_url,
        api_key=settings.api_key,
        default_parameters={"temperature": 1},
        timeout_seconds=DEFAULT_EVAL_TIMEOUT,
        http_client=client,
    )


def _is_transient_status(status_code: int) -> bool:
    return status_code in (408, 429) or 500 <= status_code <= 599


def classify_provider_exception(exc: BaseException) -> EvalOutcomeKind:
    if isinstance(exc, ProviderError):
        code_num = int(exc.code) if exc.code and exc.code.isdigit() else 0
        if exc.retryable and code_num != 409:
            return EvalOutcomeKind.INFRA_ERROR
        if _is_transient_status(code_num):
            return EvalOutcomeKind.INFRA_ERROR
        return EvalOutcomeKind.FAILED
    if isinstance(exc, httpx.HTTPStatusError):
        if _is_transient_status(exc.response.status_code):
            return EvalOutcomeKind.INFRA_ERROR
        return EvalOutcomeKind.FAILED
    if isinstance(exc, (httpx.TransportError, TimeoutError)):
        return EvalOutcomeKind.INFRA_ERROR
    return EvalOutcomeKind.FAILED


def _extract_json_dict(cleaned: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    starts = [idx for idx, ch in enumerate(cleaned) if ch == "{"]
    for idx in reversed(starts):
        try:
            obj, _ = decoder.raw_decode(cleaned[idx:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "grounded" in obj:
            return obj
    return None


def parse_judge_verdict(raw_text: str, rubric: str = "") -> JudgeVerdict:
    cleaned = raw_text.strip()
    data = _extract_json_dict(cleaned)
    if data is None:
        snippet = cleaned[:100]
        return JudgeVerdict(passed=False, reason=f"invalid JSON: {snippet}")
    grounded = data.get("grounded") is True
    concise = data.get("concise") is True
    rubric_ok = (
        data.get("rubric_ok") is True
        if rubric.strip()
        else data.get("rubric_ok", True) is True
    )
    reason = str(data.get("reason", ""))
    passed = grounded and concise and rubric_ok
    return JudgeVerdict(passed=passed, reason=reason)


async def judge_delivery(
    provider: ModelProvider, item: JudgeInput
) -> JudgeVerdict:
    system = (
        "You are a strict delivery evaluator. Inspect ONLY user query, "
        "tool evidence, and delivered reply. Return ONLY JSON: "
        '{"grounded": bool, "concise": bool, "rubric_ok": bool, '
        '"reason": "short"}. grounded=false if ANY claim, ID, SHA, or status '
        "in delivered_text lacks tool evidence. concise=false if reply uses "
        "filler preamble or bloated boilerplate."
    )
    user_msg = (
        f"USER_QUERY:\n{item.query}\n\n"
        f"TOOL_EVIDENCE:\n{item.evidence}\n\n"
        f"DELIVERED_TEXT:\n{item.delivered_text}\n\n"
        f"EXTRA_RUBRIC:\n{item.rubric or 'None'}"
    )
    resp = await provider.complete(
        CandidateRequest(
            session_id="eval_judge",
            turn=1,
            step=1,
            messages=(
                Message(role="system", content=system),
                Message(role="user", content=user_msg),
            ),
            tools=(),
        ),
        attempt=1,
        cancel=asyncio.Event(),
    )
    return parse_judge_verdict(resp.content, rubric=item.rubric)


async def _run_once(
    feature: str,
    case_id: str,
    fn: Callable[[], Awaitable[tuple[bool, str]]],
) -> EvalCaseResult:
    try:
        ok, detail = await fn()
    except (
        ProviderError,
        httpx.HTTPError,
        TimeoutError,
        AssertionError,
        RuntimeError,
        ValueError,
    ) as exc:
        kind = classify_provider_exception(exc)
        return EvalCaseResult(
            feature, case_id, kind, f"{type(exc).__name__}: {exc}"
        )
    kind = EvalOutcomeKind.PASSED if ok else EvalOutcomeKind.FAILED
    return EvalCaseResult(feature, case_id, kind, detail)


async def run_case_with_retry(
    feature: str,
    case_id: str,
    fn: Callable[[], Awaitable[tuple[bool, str]]],
    max_attempts: int = 4,
) -> EvalCaseResult:
    result = await _run_once(feature, case_id, fn)
    attempt = 1
    while (
        result.outcome == EvalOutcomeKind.INFRA_ERROR and attempt < max_attempts
    ):
        await asyncio.sleep(0.8 * attempt)
        attempt += 1
        result = await _run_once(feature, case_id, fn)
    return result
