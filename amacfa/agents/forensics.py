"""Combine invoice rules and graph traversal evidence."""

from amacfa.models import Evidence, Policy
from amacfa.tools.anomaly import detect_anomalies
from amacfa.tools.relationships import RelationshipSearch
from amacfa.workflows.state import AuditState


def forensic_agent(state: AuditState, policy: Policy, search: RelationshipSearch) -> dict:
    rows = [Evidence.model_validate(row) for row in state["rows"]]
    signals = detect_anomalies(rows, policy) + search(state["audit_id"], rows)
    signals.sort(key=lambda signal: (signal.rule, signal.lines))
    return {"signals": [signal.model_dump(mode="json") for signal in signals]}
