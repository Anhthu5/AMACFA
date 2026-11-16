"""Check accounting boundaries, vector parity and actual Neo4j traversal."""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from amacfa.config import Settings
from amacfa.models import Rule
from amacfa.tools.anomaly import detect_anomalies
from amacfa.tools.invoices import InvoiceInputError, parse_invoice_csv
from amacfa.tools.policy import load_policy, make_related_search
from amacfa.tools.relationships import relationship_search
from main import create_app


def test_amount_dates_and_record_limits(mixed):
    rows = parse_invoice_csv(mixed, 10)
    assert str(rows[0].invoice.amount) == "3500.00"
    assert str(rows[1].invoice.amount) == "3500.00"
    assert rows[1].invoice.vendor_id == "ACME"
    assert rows[1].line == 3
    for data in [
        mixed.replace(b"250000000,", b"250000000.01,"),
        mixed.replace(b"2026-09-01", b"2026-09-31"),
        mixed.replace(b"3500.00", b"1e9"),
        mixed.replace(b"3500.00", b"0"),
        mixed.replace(b"ACME,", b'"ACME\nBUYER",'),
    ]:
        with pytest.raises(InvoiceInputError, match="Line 2|Line 10"):
            parse_invoice_csv(data, 10)
    with pytest.raises(InvoiceInputError, match="limit"):
        parse_invoice_csv(mixed, 9)


def test_threshold_and_currency_boundaries(mixed, clean):
    policy, _ = load_policy()
    at_limit = clean.replace(b",FIN-3,BANK-E", b",,BANK-E", 1)
    signals = detect_anomalies(parse_invoice_csv(at_limit, 20), policy)
    assert [(signal.rule, signal.lines) for signal in signals] == [(Rule.MISSING_APPROVAL, [2])]

    for changed in (
        mixed.replace(b"2026-09-11,4100", b"2026-09-12,4100"),
        mixed.replace(b"4100.00,USD", b"4100.00,EUR"),
        mixed.replace(b"4100.00,USD,BUYER-4", b"4100.00,USD,BUYER-9"),
        mixed.replace(b"INV-411,", b"INV-410,"),
        mixed.replace(b"4100.00,USD", b"3799.99,USD"),
    ):
        signals = detect_anomalies(parse_invoice_csv(changed, 20), policy)
        assert not any(signal.rule == Rule.SPLIT for signal in signals)


def test_settings_reject_shared_credentials():
    with pytest.raises(ValidationError, match="distinct"):
        Settings(_env_file=None, analyst_token="same", reviewer_token="same")
    with pytest.raises(ValidationError, match="independent"):
        Settings(_env_file=None, demo_mode=False)


def test_chroma_matches_local_retrieval(tmp_path):
    pytest.importorskip("chromadb")
    policy, digest = load_policy()
    local = make_related_search(policy, digest, "local", tmp_path)
    chroma = make_related_search(policy, digest, "chroma", tmp_path)
    matches = [chroma(control) for control in policy.controls]
    assert matches == [local(control) for control in policy.controls]
    assert any(matches)
    assert (tmp_path / "chroma" / "chroma.sqlite3").is_file()


@pytest.mark.skipif(not os.getenv("AMACFA_TEST_NEO4J_URI"), reason="Neo4j test server unavailable")
def test_neo4j_isolates_cases_and_replays_idempotently(settings, mixed):
    pytest.importorskip("neo4j")
    password = os.environ["AMACFA_TEST_NEO4J_PASSWORD"]
    graph = Settings(
        _env_file=None,
        demo_mode=True,
        state_dir=settings.state_dir,
        vector_backend="local",
        graph_backend="neo4j",
        neo4j_uri=os.environ["AMACFA_TEST_NEO4J_URI"],
        neo4j_password=password,
        llm_backend="offline",
    )
    matched = parse_invoice_csv(mixed, 20)
    one_vendor = parse_invoice_csv(mixed.replace(b"SOUTH,INV", b"NORTH,INV"), 20)
    with relationship_search(graph) as search:
        audit_id = str(uuid4())
        initial = search(audit_id, matched)
        assert len(initial) == 1 and initial[0].lines == [8, 9]
        assert search(audit_id, matched) == initial
        assert search(str(uuid4()), one_vendor) == []

    with TestClient(create_app(graph)) as client:
        response = client.post(
            "/audits",
            content=mixed,
            headers={
                "Authorization": f"Bearer {graph.analyst_token.get_secret_value()}",
                "Content-Type": "text/csv",
                "Idempotency-Key": str(uuid4()),
            },
        ).raise_for_status()
        packet = response.json()["packet"]
        assert packet["graph_backend"] == "neo4j"
        shared = next(item for item in packet["findings"] if item["rule"] == Rule.SHARED_ACCOUNT)
        assert shared["lines"] == [8, 9] and shared["control"]["id"] == "AP-05"
