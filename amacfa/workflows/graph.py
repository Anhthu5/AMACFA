"""Four specialized stages and a durable human review gate."""

import logging
from collections.abc import Callable
from functools import partial
from time import perf_counter
from typing import Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from amacfa.agents.compliance import compliance_agent
from amacfa.agents.forensics import forensic_agent
from amacfa.agents.ingestion import data_ingestion
from amacfa.agents.reporting import executive_reporting
from amacfa.models import Policy, Review, StageEvent
from amacfa.tools.llm import Ranker
from amacfa.tools.policy import RelatedSearch
from amacfa.tools.relationships import RelationshipSearch
from amacfa.workflows.state import AuditState

LOGGER = logging.getLogger("uvicorn.error").getChild("amacfa.stages")


def _instrument(stage: str, node: Callable[[AuditState], dict], count: Callable[[dict], int]):
    def execute(state: AuditState) -> dict:
        started = perf_counter()
        result = node(state)
        event = StageEvent(
            stage=stage, count=count(result), elapsed_ms=round((perf_counter() - started) * 1000)
        )
        LOGGER.info(
            "audit=%s stage=%s count=%d elapsed_ms=%d",
            state["audit_id"],
            stage,
            event.count,
            event.elapsed_ms,
        )
        return result | {"events": [*state.get("events", []), event.model_dump(mode="json")]}

    return execute


def _review(state: AuditState) -> dict:
    # An interrupted node restarts on resume. Keep side effects outside this function.
    reply = interrupt(
        {
            "audit_id": state["audit_id"],
            "packet_sha256": state["packet_sha256"],
            "findings": len(state["packet"]["findings"]),
        }
    )
    review = Review.model_validate(reply)
    if review.actor != "reviewer" or review.packet_sha256 != state["packet_sha256"]:
        raise ValueError("Review does not match the pending evidence packet.")
    return {"review": review.model_dump(mode="json")}


def _next_after_review(state: AuditState) -> Literal["executive_reporting", "__end__"]:
    return "executive_reporting" if state["review"]["decision"] == "approve" else END


def build_graph(
    *,
    policy: Policy,
    relationships: RelationshipSearch,
    related: RelatedSearch,
    ranker: Ranker,
    checkpointer: BaseCheckpointSaver,
):
    graph = StateGraph(AuditState)
    graph.add_node(
        "data_ingestion",
        _instrument("data_ingestion", data_ingestion, lambda result: len(result["rows"])),
    )
    graph.add_node(
        "forensics",
        _instrument(
            "forensics",
            partial(forensic_agent, policy=policy, search=relationships),
            lambda result: len(result["signals"]),
        ),
    )
    graph.add_node(
        "compliance",
        _instrument(
            "compliance",
            partial(compliance_agent, policy=policy, search=related),
            lambda result: len(result["packet"]["findings"]),
        ),
    )
    graph.add_node("human_review", _instrument("human_review", _review, lambda _: 1))
    graph.add_node(
        "executive_reporting",
        _instrument(
            "executive_reporting",
            partial(executive_reporting, ranker=ranker),
            lambda result: len(result["report"]["priority_finding_ids"]),
        ),
    )
    graph.add_edge(START, "data_ingestion")
    graph.add_edge("data_ingestion", "forensics")
    graph.add_edge("forensics", "compliance")
    graph.add_edge("compliance", "human_review")
    graph.add_conditional_edges("human_review", _next_after_review)
    graph.add_edge("executive_reporting", END)
    return graph.compile(checkpointer=checkpointer)
