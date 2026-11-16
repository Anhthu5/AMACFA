"""Serialize mutations per case and recover a started case from its checkpoint."""

from datetime import UTC, datetime
from threading import RLock
from uuid import UUID

from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command, StateSnapshot
from langsmith import tracing_context

from amacfa.config import Settings
from amacfa.models import AuditView, Policy, Review, ReviewRequest, sha256
from amacfa.tools.invoices import parse_invoice_csv
from amacfa.workflows.state import AuditState


class AuditNotFound(LookupError):
    """No checkpoint exists for the requested audit."""


class AuditConflict(RuntimeError):
    """The case cannot accept the requested mutation."""


class AuditService:
    def __init__(
        self, graph: CompiledStateGraph, settings: Settings, policy: Policy, policy_sha256: str
    ) -> None:
        self.graph = graph
        self.settings = settings
        self.policy = policy
        self.policy_sha256 = policy_sha256
        # Bound lock memory. Uvicorn runs one worker for this SQLite deployment.
        self._locks = [RLock() for _ in range(64)]

    def _lock(self, audit_id: UUID):
        return self._locks[audit_id.int % len(self._locks)]

    @staticmethod
    def _config(audit_id: UUID) -> RunnableConfig:
        return {"configurable": {"thread_id": str(audit_id)}}

    def start(self, audit_id: UUID, data: bytes) -> AuditView:
        config = self._config(audit_id)
        digest = sha256(data)
        with self._lock(audit_id):
            snapshot = self.graph.get_state(config)
            if not snapshot.values:
                rows = parse_invoice_csv(data, self.settings.max_rows)
                state: AuditState = {
                    "audit_id": str(audit_id),
                    "input_sha256": digest,
                    "policy_version": self.policy.version,
                    "policy_sha256": self.policy_sha256,
                    "graph_backend": self.settings.graph_backend,
                    "vector_backend": self.settings.vector_backend,
                    "rows": [row.model_dump(mode="json") for row in rows],
                    "events": [],
                }
                self._invoke(state, config)
            else:
                if digest != snapshot.values["input_sha256"]:
                    raise AuditConflict("Idempotency-Key already belongs to a different CSV.")
                # A start retry can advance pre-review work but cannot resume a review.
                if snapshot.next and not snapshot.interrupts and "review" not in snapshot.values:
                    if "packet" not in snapshot.values:
                        self._require_original_pipeline(snapshot)
                    self._invoke(None, config)
            return self._view(self.graph.get_state(config))

    def get(self, audit_id: UUID) -> AuditView:
        return self._view(self.graph.get_state(self._config(audit_id)))

    def review(self, audit_id: UUID, request: ReviewRequest, packet_sha256: str) -> AuditView:
        config = self._config(audit_id)
        with self._lock(audit_id):
            snapshot = self.graph.get_state(config)
            view = self._view(snapshot)
            if packet_sha256 != view.packet_sha256:
                raise AuditConflict("The supplied packet digest does not match this audit.")
            if view.review:
                if (request.decision, request.note) != (view.review.decision, view.review.note):
                    raise AuditConflict("A different review has already been recorded.")
                if snapshot.next:
                    self._invoke(None, config)
            elif view.status == "awaiting_review":
                review = Review(
                    **request.model_dump(),
                    actor="reviewer",
                    reviewed_at=datetime.now(UTC),
                    packet_sha256=packet_sha256,
                )
                self._invoke(Command(resume=review.model_dump(mode="json")), config)
            else:
                raise AuditConflict("This audit is not awaiting review.")
            return self._view(self.graph.get_state(config))

    def _invoke(self, value: AuditState | Command | None, config: RunnableConfig) -> None:
        # Checkpoints contain financial data. Disable LangSmith export for these runs.
        with tracing_context(enabled=False):
            self.graph.invoke(value, config, durability="sync")

    def _require_original_pipeline(self, snapshot: StateSnapshot) -> None:
        for field, current in (
            ("policy_sha256", self.policy_sha256),
            ("graph_backend", self.settings.graph_backend),
            ("vector_backend", self.settings.vector_backend),
        ):
            if snapshot.values[field] != current:
                raise AuditConflict("Restore the original policy and evidence backends.")

    @staticmethod
    def _view(snapshot: StateSnapshot) -> AuditView:
        values = snapshot.values
        if not values or "audit_id" not in values:
            raise AuditNotFound("Audit not found.")
        if values.get("report") is not None:
            status = "completed"
        elif values.get("review", {}).get("decision") == "return":
            status = "returned"
        elif snapshot.interrupts:
            status = "awaiting_review"
        else:
            status = "processing"
        return AuditView.model_validate(
            {
                "audit_id": values["audit_id"],
                "status": status,
                "input_sha256": values["input_sha256"],
                "policy_version": values["policy_version"],
                "packet_sha256": values.get("packet_sha256"),
                "packet": values.get("packet"),
                "events": values.get("events", []),
                "review": values.get("review"),
                "report": values.get("report"),
            }
        )
