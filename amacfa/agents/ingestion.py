"""The ingestion stage verifies canonicalized evidence before the next handoff."""

from amacfa.models import Evidence, canonical_digest
from amacfa.workflows.state import AuditState


def data_ingestion(state: AuditState) -> dict:
    for record in state["rows"]:
        row = Evidence.model_validate(record)
        if canonical_digest(row.invoice.model_dump(mode="json")) != row.row_sha256:
            raise ValueError("Evidence hash mismatch during ingestion.")
    return {"rows": state["rows"]}
