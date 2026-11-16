"""FastAPI entry point for the AMACFA audit workflow."""

import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import ExitStack, asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langgraph.checkpoint.sqlite import SqliteSaver

from amacfa.config import Settings
from amacfa.models import AuditView, EvidenceBackendError, ReviewRequest, Role
from amacfa.tools.invoices import InvoiceInputError
from amacfa.tools.llm import build_ranker
from amacfa.tools.policy import load_policy, make_related_search
from amacfa.tools.relationships import relationship_search
from amacfa.workflows.graph import build_graph
from amacfa.workflows.service import AuditConflict, AuditNotFound, AuditService

LOGGER = logging.getLogger("uvicorn.error").getChild("amacfa")
BEARER = HTTPBearer(auto_error=False)
Token = Annotated[HTTPAuthorizationCredentials | None, Depends(BEARER)]


def authorize(allowed: tuple[Role, ...], request: Request, token: Token) -> None:
    settings: Settings = request.app.state.settings
    supplied = token.credentials.encode("utf-8") if token else b""
    for role, expected in (
        ("analyst", settings.analyst_token),
        ("reviewer", settings.reviewer_token),
    ):
        if hmac.compare_digest(supplied, expected.get_secret_value().encode("ascii")):
            if role in allowed:
                return
            raise HTTPException(403, "This role cannot perform the requested action.")
    raise HTTPException(401, "Valid bearer token required.", headers={"WWW-Authenticate": "Bearer"})


def allow_analyst(request: Request, token: Token) -> None:
    authorize(("analyst",), request, token)


def allow_reviewer(request: Request, token: Token) -> None:
    authorize(("reviewer",), request, token)


def allow_read(request: Request, token: Token) -> None:
    authorize(("analyst", "reviewer"), request, token)


def get_service(request: Request) -> AuditService:
    return request.app.state.audit_service


Service = Annotated[AuditService, Depends(get_service)]
DigestHeader = Annotated[str, Header(alias="X-Review-Packet-SHA256", pattern=r"^[a-f0-9]{64}$")]
CSV_BODY = {
    "requestBody": {
        "required": True,
        "content": {
            "text/csv": {
                "schema": {"type": "string"},
                "example": (
                    "vendor_id,invoice_number,issued_on,amount,currency,requested_by,approved_by,account_token\n"
                    "V001,INV-001,2026-09-01,12000.00,USD,REQ-01,,BANK-TOKEN-1\n"
                ),
            }
        },
    }
}


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        config = settings or Settings()
        config.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        policy, digest = load_policy()
        with ExitStack() as stack:
            saver = stack.enter_context(
                SqliteSaver.from_conn_string(str(config.state_dir / "checkpoints.sqlite3"))
            )
            relationships = stack.enter_context(relationship_search(config))
            ranker = stack.enter_context(build_ranker(config))
            graph = build_graph(
                policy=policy,
                relationships=relationships,
                ranker=ranker,
                checkpointer=saver,
                related=make_related_search(
                    policy, digest, config.vector_backend, config.state_dir
                ),
            )
            application.state.settings = config
            application.state.audit_service = AuditService(graph, config, policy, digest)
            yield

    app = FastAPI(
        title="AMACFA · Corporate Forensic & Compliance Auditor",
        version="1.0.0",
        description="Invoice evidence, versioned controls, human review, and executive reporting.",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def disable_cache(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_: Request, exc: RequestValidationError):
        errors = [{"loc": item["loc"], "type": item["type"]} for item in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": errors})

    @app.exception_handler(InvoiceInputError)
    async def invalid_csv(_: Request, exc: InvoiceInputError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    @app.exception_handler(AuditNotFound)
    async def missing_audit(_: Request, exc: AuditNotFound):
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(AuditConflict)
    async def audit_conflict(_: Request, exc: AuditConflict):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(EvidenceBackendError)
    async def evidence_unavailable(_: Request, exc: EvidenceBackendError):
        LOGGER.warning("evidence_backend_error type=%s", type(exc.__cause__).__name__)
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.get("/healthz", tags=["ops"])
    def health():
        return {"status": "ok"}

    @app.post(
        "/audits",
        tags=["audit"],
        dependencies=[Depends(allow_analyst)],
        openapi_extra=CSV_BODY,
        response_model=AuditView,
    )
    async def start_audit(
        request: Request,
        service: Service,
        audit_id: Annotated[UUID, Header(alias="Idempotency-Key")],
    ):
        if request.headers.get("content-type", "").partition(";")[0].strip().lower() != "text/csv":
            raise HTTPException(415, "Use Content-Type: text/csv.")
        payload = bytearray()
        async for chunk in request.stream():
            if len(payload) + len(chunk) > service.settings.max_upload_bytes:
                raise HTTPException(413, "CSV exceeds the upload limit.")
            payload.extend(chunk)
        return await run_in_threadpool(service.start, audit_id, bytes(payload))

    @app.get(
        "/audits/{audit_id}",
        tags=["audit"],
        dependencies=[Depends(allow_read)],
        response_model=AuditView,
    )
    def get_audit(audit_id: UUID, service: Service):
        return service.get(audit_id)

    @app.post(
        "/audits/{audit_id}/review",
        tags=["review"],
        dependencies=[Depends(allow_reviewer)],
        response_model=AuditView,
    )
    def review_audit(audit_id: UUID, body: ReviewRequest, packet: DigestHeader, service: Service):
        return service.review(audit_id, body, packet)

    @app.get(
        "/audits/{audit_id}/report.md",
        tags=["audit"],
        dependencies=[Depends(allow_read)],
        response_class=PlainTextResponse,
    )
    def get_report(audit_id: UUID, service: Service):
        audit = service.get(audit_id)
        if audit.report is None:
            raise HTTPException(409, "Executive report has not been published.")
        return PlainTextResponse(
            audit.report.markdown,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="audit-{audit_id}.md"'},
        )

    return app


app = create_app()
