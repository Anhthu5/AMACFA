"""Validate structured SDK payloads with mock HTTP and constrain model output."""

import importlib
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from amacfa.config import DEMO_ANALYST, DEMO_REVIEWER, Settings
from amacfa.models import AuditView
from amacfa.tools.llm import PrioritySelection, rank_with_provider
from main import create_app


def _post_case(client, mixed):
    response = client.post(
        "/audits",
        content=mixed,
        headers={
            "Authorization": f"Bearer {DEMO_ANALYST}",
            "Content-Type": "text/csv",
            "Idempotency-Key": str(uuid4()),
        },
    )
    return AuditView.model_validate(response.raise_for_status().json())


@pytest.mark.parametrize("failure", ["unknown", "duplicate", "severity", "timeout", "refusal"])
def test_model_cannot_invent_alter_severity_or_block_publication(client, mixed, failure):
    pending = _post_case(client, mixed)
    findings = pending.packet.findings

    def choose(_):
        if failure == "timeout":
            raise TimeoutError("provider timed out")
        if failure == "refusal":
            return None
        result = {
            "unknown": ["invented", "F-0002", "F-0004"],
            "duplicate": ["F-0001"] * 3,
            "severity": ["F-0003", "F-0001", "F-0002"],
        }
        return PrioritySelection(finding_ids=result[failure])

    ranked = rank_with_provider(findings, choose, "openai", "test", (TimeoutError,))
    assert ranked.ids == ["F-0001", "F-0002", "F-0004"]
    assert ranked.source == "fallback"


@pytest.mark.parametrize("backend,factory", [("openai", "OpenAI"), ("anthropic", "Anthropic")])
def test_provider_sdk_structured_output_and_data_boundary(
    backend, factory, monkeypatch, tmp_path, mixed
):
    pytest.importorskip(backend)
    sdk = importlib.import_module(backend)
    real_client = getattr(sdk, factory)
    requests = []
    chosen = ["F-0005", "F-0002", "F-0001"]

    def handle(request):
        requests.append(request)
        body = json.loads(request.content)
        content = json.dumps({"finding_ids": chosen})
        for sensitive in ("BANK-X", "BUYER-1", "ACME", "12000", "private review note"):
            assert sensitive not in request.content.decode("utf-8")
        if backend == "openai":
            assert request.url.path == "/v1/responses"
            assert body["store"] is False
            assert "finding_ids" in body["text"]["format"]["schema"]["properties"]
            response = {
                "id": "resp_test",
                "object": "response",
                "model": body["model"],
                "created_at": 0,
                "status": "completed",
                "parallel_tool_calls": False,
                "tool_choice": "auto",
                "tools": [],
                "output": [
                    {
                        "id": "msg_test",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {
                                "type": "output_text",
                                "annotations": [],
                                "text": content,
                            }
                        ],
                    }
                ],
            }
        else:
            assert request.url.path == "/v1/messages"
            assert "finding_ids" in body["output_config"]["format"]["schema"]["properties"]
            response = {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "model": body["model"],
                "content": [{"type": "text", "text": content}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 10, "output_tokens": 10},
            }
        return httpx.Response(200, json=response)

    def fake_client(**kwargs):
        return real_client(
            **kwargs, http_client=httpx.Client(transport=httpx.MockTransport(handle))
        )

    monkeypatch.setattr(sdk, factory, fake_client)
    settings = Settings(
        _env_file=None,
        state_dir=tmp_path,
        llm_backend=backend,
        llm_model="test-model",
        graph_backend="local",
        vector_backend="local",
        demo_mode=True,
        OPENAI_API_KEY="synthetic",
        ANTHROPIC_API_KEY="synthetic",
        analyst_token=DEMO_ANALYST,
        reviewer_token=DEMO_REVIEWER,
    )
    with TestClient(create_app(settings)) as client:
        pending = _post_case(client, mixed)
        assert requests == []
        response = client.post(
            f"/audits/{pending.audit_id}/review",
            headers={
                "Authorization": f"Bearer {DEMO_REVIEWER}",
                "X-Review-Packet-SHA256": pending.packet_sha256,
            },
            json={"decision": "approve", "note": "private review note"},
        ).raise_for_status()
    case = AuditView.model_validate(response.json())
    assert len(requests) == 1
    assert case.status == "completed"
    assert case.packet == pending.packet
    assert case.report.ranking_source == backend
    assert case.report.priority_finding_ids == chosen
