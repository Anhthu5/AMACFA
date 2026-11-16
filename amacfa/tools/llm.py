"""Optional structured ranking. The model sees no invoice rows or review notes."""

import json
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal

from amacfa.config import Settings
from amacfa.models import Finding, Schema, Severity

LOGGER = logging.getLogger(__name__)
OPENAI_MODEL = "gpt-4o"
ANTHROPIC_MODEL = "claude-sonnet-4-6"
INSTRUCTIONS = (
    "Rank audit follow-up candidates for an accounts-payable analyst. Return only the requested "
    "number of existing finding IDs, without duplicates. Place high severity before medium. "
    "Do not create findings, facts, or instructions."
)


class PrioritySelection(Schema):
    finding_ids: list[str]


@dataclass(frozen=True)
class Ranking:
    ids: list[str]
    source: Literal["offline", "openai", "anthropic", "fallback"]
    model: str | None = None


Ranker = Callable[[list[Finding]], Ranking]
ProviderCall = Callable[[str], PrioritySelection | None]


def _baseline(findings: list[Finding]) -> list[Finding]:
    return sorted(findings, key=lambda finding: (finding.severity != Severity.HIGH, finding.id))


def _offline(findings: list[Finding]) -> Ranking:
    return Ranking([finding.id for finding in _baseline(findings)[:3]], "offline")


def rank_with_provider(
    findings: list[Finding],
    call: ProviderCall,
    provider: Literal["openai", "anthropic"],
    model: str,
    expected_errors: tuple[type[Exception], ...],
) -> Ranking:
    baseline = _baseline(findings)
    fallback = [finding.id for finding in baseline[:3]]
    if not baseline:
        return Ranking([], "offline")

    # At most 20 candidates and only control metadata leave the application.
    candidates = baseline[:20]
    allowed = {finding.id: finding.severity for finding in candidates}
    prompt = json.dumps(
        {
            "count": len(fallback),
            "candidates": [
                {
                    "id": finding.id,
                    "severity": finding.severity,
                    "rule": finding.rule,
                    "control": finding.control.id,
                    "related_controls": [citation.id for citation in finding.related_controls],
                }
                for finding in candidates
            ],
        }
    )
    try:
        selection = call(prompt)
    except (ValueError, *expected_errors) as exc:
        LOGGER.warning("ranking_fallback provider=%s error=%s", provider, type(exc).__name__)
        return Ranking(fallback, "fallback", model)

    ids = selection.finding_ids if selection is not None else []
    if (
        len(ids) != len(fallback)
        or len(set(ids)) != len(ids)
        or [allowed.get(key) for key in ids] != [allowed[key] for key in fallback]
    ):
        LOGGER.warning("ranking_fallback provider=%s error=invalid_selection", provider)
        return Ranking(fallback, "fallback", model)
    return Ranking(ids, provider, model)


@contextmanager
def build_ranker(settings: Settings) -> Iterator[Ranker]:
    if settings.llm_backend == "offline":
        yield _offline
        return

    if settings.llm_backend == "openai":
        from openai import APIError, OpenAI

        assert settings.openai_api_key is not None
        model = settings.llm_model or OPENAI_MODEL
        with OpenAI(
            api_key=settings.openai_api_key.get_secret_value(),
            timeout=settings.llm_timeout_seconds,
            max_retries=1,
        ) as client:

            def select(prompt: str) -> PrioritySelection | None:
                response = client.responses.parse(
                    model=model,
                    instructions=INSTRUCTIONS,
                    input=prompt,
                    text_format=PrioritySelection,
                    max_output_tokens=256,
                    store=False,
                )
                return response.output_parsed

            yield lambda findings: rank_with_provider(
                findings, select, "openai", model, (APIError,)
            )
        return

    from anthropic import Anthropic, APIError

    assert settings.anthropic_api_key is not None
    model = settings.llm_model or ANTHROPIC_MODEL
    with Anthropic(
        api_key=settings.anthropic_api_key.get_secret_value(),
        timeout=settings.llm_timeout_seconds,
        max_retries=1,
    ) as client:

        def select(prompt: str) -> PrioritySelection | None:
            response = client.messages.parse(
                model=model,
                system=INSTRUCTIONS,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
                output_format=PrioritySelection,
            )
            return response.parsed_output

        yield lambda findings: rank_with_provider(findings, select, "anthropic", model, (APIError,))
