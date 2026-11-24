from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from nextloop import HarnessError, ProviderError

from nika.contracts import (
    EXPECTED_EVENT_SCHEMA,
    EXPECTED_NEXTLOOP_API,
    IngressEnvelope,
    IngressSource,
    ReplyKind,
    ReplyTarget,
    ReportStatus,
    SessionIdentity,
    SpecialistId,
    TaskKind,
    TaskStatus,
    verify_nextloop_version,
)
from nika.eval_runner import (
    EvalOutcomeKind,
    LiveProviderSettings,
    build_http_client,
    classify_provider_exception,
    load_provider_settings,
    parse_judge_verdict,
)


def test_version_pin_matches_installed_nextloop() -> None:
    verify_nextloop_version()
    with pytest.raises(HarnessError, match="nextloop API mismatch"):
        verify_nextloop_version(
            api_version="0.9.0", event_schema=EXPECTED_EVENT_SCHEMA
        )
    with pytest.raises(HarnessError, match="event schema mismatch"):
        verify_nextloop_version(
            api_version=EXPECTED_NEXTLOOP_API, event_schema="9.9"
        )


def test_core_contracts_validate_and_redact_secrets() -> None:
    target = ReplyTarget(
        kind=ReplyKind.POCKET_CALLBACK,
        callback_url=" https://pocket.example.com/cb ",
        callback_token="cbk_super_secret",
        metadata={"todo_id": "t1"},
    )
    assert target.callback_url == "https://pocket.example.com/cb"
    assert "cbk_super_secret" not in repr(target)
    with pytest.raises(TypeError):
        target.metadata["x"] = "mutated"  # type: ignore[index]

    envelope = IngressEnvelope(
        event_id=" feishu:om_1 ",
        source=IngressSource.FEISHU,
        thread_key=" feishu:dm:oc_test ",
        prompt=" hello ",
        reply_target=ReplyTarget(
            kind=ReplyKind.FEISHU_CARD, channel_id="oc_test"
        ),
    )
    assert envelope.event_id == "feishu:om_1"
    assert envelope.thread_key == "feishu:dm:oc_test"

    identity = SessionIdentity(
        session_id="sess_1",
        task_id="task_1",
        specialist=SpecialistId.MAIN,
        kind=TaskKind.INGRESS,
        depth=0,
    )
    assert identity.depth == 0
    assert TaskStatus.RUNNING.value == "running"
    assert ReportStatus.DONE.value == "done"

    with pytest.raises(ValueError, match="depth"):
        SessionIdentity(
            session_id="sess_2",
            task_id="task_2",
            specialist=SpecialistId.TOP_TALENT,
            kind=TaskKind.CONSULT,
            depth=2,
        )


def test_eval_infra_vs_behavior_classification() -> None:
    err_500 = ProviderError(
        "OpenAI HTTP 500: internal", retryable=False, code="500"
    )
    assert classify_provider_exception(err_500) == EvalOutcomeKind.INFRA_ERROR

    err_409 = ProviderError("Conflict 409", retryable=False, code="409")
    assert classify_provider_exception(err_409) == EvalOutcomeKind.FAILED

    req = httpx.Request("POST", "https://api.example.com/v1")
    resp_503 = httpx.Response(503, request=req)
    status_err = httpx.HTTPStatusError("503", request=req, response=resp_503)
    assert (
        classify_provider_exception(status_err) == EvalOutcomeKind.INFRA_ERROR
    )


def test_provider_settings_and_tls_fail_closed(tmp_path: Path) -> None:
    settings = LiveProviderSettings(
        base_url="https://api.example.com/v1",
        api_key="my_secret_token",
        ca_bundle=str(tmp_path / "missing.pem"),
    )
    assert "my_secret_token" not in repr(settings)
    with pytest.raises(FileNotFoundError, match="ca_bundle"):
        build_http_client(settings)

    with pytest.raises(ValueError, match="partial"):
        load_provider_settings(
            {"NIKA_EVAL_BASE_URL": "https://api.example.com/v1"},
            tmp_path / "none.json",
        )


def test_judge_verdict_parser_strict_rubric_and_prose_braces() -> None:
    prose = (
        "Note {ref}\n"
        '{"grounded": true, "concise": true, "rubric_ok": true, "reason": "ok"}'
    )
    parsed = parse_judge_verdict(prose, rubric="must cite rev")
    assert parsed.passed is True

    missing_rubric = parse_judge_verdict(
        '{"grounded": true, "concise": true, "reason": "omitted rubric"}',
        rubric="must cite rev",
    )
    assert missing_rubric.passed is False

    unfaithful = parse_judge_verdict(
        '{"grounded": false, "concise": true, "reason": "invented sha"}'
    )
    assert unfaithful.passed is False
    assert parse_judge_verdict("not json at all").passed is False
