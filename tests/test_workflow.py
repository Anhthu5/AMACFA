"""Exercise the real HTTP and LangGraph case lifecycle."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import main
from amacfa.config import DEMO_ANALYST, DEMO_REVIEWER
from amacfa.models import AuditView, EvidenceBackendError, canonical_digest, sha256

ANALYST = {"Authorization": f"Bearer {DEMO_ANALYST}"}
REVIEWER = {"Authorization": f"Bearer {DEMO_REVIEWER}"}


def start(client, audit_id, csv, headers=None):
    return client.post(
        "/audits",
        content=csv,
        headers=(ANALYST if headers is None else headers)
        | {
            "Content-Type": "text/csv",
            "Idempotency-Key": str(audit_id),
        },
    )


def review(client, case, decision="approve", headers=None, digest=None):
    return client.post(
        f"/audits/{case.audit_id}/review",
        headers=(REVIEWER if headers is None else headers)
        | {
            "X-Review-Packet-SHA256": digest or case.packet_sha256,
        },
        json={"decision": decision, "note": "Evidence independently verified."},
    )


def test_approval_survives_restart(settings, mixed):
    audit_id = uuid4()
    url = f"/audits/{audit_id}/report.md"
    with TestClient(main.create_app(settings)) as client:
        pending = AuditView.model_validate(start(client, audit_id, mixed).raise_for_status().json())
        assert pending.status == "awaiting_review"
        assert len(pending.packet.findings) == 5
        assert pending.input_sha256 == sha256(mixed)
        assert pending.packet_sha256 == canonical_digest(pending.packet.model_dump(mode="json"))
        assert all(
            row.row_sha256 == canonical_digest(row.invoice.model_dump(mode="json"))
            for row in pending.packet.rows
        )
        assert client.get(url, headers=ANALYST).status_code == 409

    with TestClient(main.create_app(settings)) as client:
        assert review(client, pending, headers=ANALYST).status_code == 403
        assert review(client, pending, digest="0" * 64).status_code == 409
        approved = AuditView.model_validate(review(client, pending).raise_for_status().json())
        assert approved.status == "completed"
        assert approved.review.packet_sha256 == pending.packet_sha256
        assert approved.review.actor == "reviewer"
        assert approved.packet == pending.packet
        assert [event.stage for event in approved.events] == [
            "data_ingestion",
            "forensics",
            "compliance",
            "human_review",
            "executive_reporting",
        ]
        assert review(client, pending).json() == approved.model_dump(mode="json")
        assert review(client, pending, decision="return").status_code == 409
        response = client.get(url, headers=ANALYST).raise_for_status()
        assert response.headers["cache-control"] == "no-store"
        assert sha256(response.content) == approved.report.sha256
        assert "AP-05@AP-DEMO-1.0" in response.text
        assert "BANK-X" not in response.text


def test_return_is_terminal(client, mixed):
    case = AuditView.model_validate(start(client, uuid4(), mixed).json())
    returned = AuditView.model_validate(review(client, case, decision="return").json())
    assert returned.status == "returned"
    assert returned.report is None
    assert returned.events[-1].stage == "human_review"
    assert review(client, case).status_code == 409
    assert client.get(f"/audits/{case.audit_id}/report.md", headers=REVIEWER).status_code == 409


def test_review_digest_is_case_specific(client, mixed):
    first = AuditView.model_validate(start(client, uuid4(), mixed).raise_for_status().json())
    second = AuditView.model_validate(start(client, uuid4(), mixed).raise_for_status().json())
    assert first.input_sha256 == second.input_sha256
    assert first.packet.audit_id == first.audit_id
    assert first.packet_sha256 != second.packet_sha256
    assert review(client, second, digest=first.packet_sha256).status_code == 409


def test_idempotent_create_and_conflict(client, mixed, clean):
    audit_id = uuid4()
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(start, client, audit_id, mixed) for _ in range(2)]
        results = [future.result().raise_for_status().json() for future in futures]
    assert results[0] == results[1]
    assert start(client, audit_id, clean).status_code == 409


def test_access_and_request_bounds(client, mixed):
    assert start(client, uuid4(), mixed, headers={}).status_code == 401
    assert start(client, uuid4(), mixed, headers=REVIEWER).status_code == 403
    assert start(client, uuid4(), b"x" * 1025).status_code == 413
    assert client.get(f"/audits/{uuid4()}", headers=ANALYST).status_code == 404
    assert (
        client.post(
            "/audits", headers=ANALYST | {"Idempotency-Key": str(uuid4())}, json={}
        ).status_code
        == 415
    )
    response = start(client, uuid4(), mixed.replace(b"3500.00", b"secret-text"))
    assert response.status_code == 422
    assert "secret-text" not in response.text


def test_evidence_failure_retries_from_checkpoint(settings, mixed, monkeypatch):
    original = main.relationship_search
    observed_ids = []

    @contextmanager
    def flaky(config):
        with original(config) as search:

            def query(audit_id, rows):
                observed_ids.append(audit_id)
                if len(observed_ids) == 1:
                    raise EvidenceBackendError("Temporary evidence service failure.")
                return search(audit_id, rows)

            yield query

    monkeypatch.setattr(main, "relationship_search", flaky)
    audit_id = uuid4()
    with TestClient(main.create_app(settings)) as client:
        assert start(client, audit_id, mixed).status_code == 503
        assert client.get(f"/audits/{audit_id}", headers=ANALYST).json()["status"] == "processing"
        retried = start(client, audit_id, mixed).raise_for_status().json()
    assert retried["status"] == "awaiting_review"
    assert observed_ids == [str(audit_id), str(audit_id)]
    assert [event["stage"] for event in retried["events"]] == [
        "data_ingestion",
        "forensics",
        "compliance",
    ]


def test_clean_batch_can_be_published(client, clean):
    case = AuditView.model_validate(start(client, uuid4(), clean).json())
    approved = AuditView.model_validate(review(client, case).json())
    assert approved.packet.findings == []
    assert approved.report.priority_finding_ids == []
    assert "0 tín hiệu" in approved.report.summary


@pytest.mark.parametrize("decision", ["approve", "return"])
def test_same_review_replay_is_idempotent(client, mixed, decision):
    case = AuditView.model_validate(start(client, uuid4(), mixed).json())
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(review, client, case, decision) for _ in range(2)]
        results = [future.result().raise_for_status().json() for future in futures]
    assert results[0] == results[1]
