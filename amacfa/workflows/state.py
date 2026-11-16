"""Persist only JSON-compatible state values in LangGraph checkpoints."""

from typing import NotRequired, TypedDict


class AuditState(TypedDict):
    audit_id: str
    input_sha256: str
    policy_version: str
    policy_sha256: str
    graph_backend: str
    vector_backend: str
    rows: list[dict]
    signals: NotRequired[list[dict]]
    packet: NotRequired[dict]
    packet_sha256: NotRequired[str]
    review: NotRequired[dict]
    report: NotRequired[dict]
    events: NotRequired[list[dict]]
