"""Load a versioned control catalog and retrieve supplementary policy passages."""

import hashlib
import math
import re
from collections.abc import Callable
from pathlib import Path

from amacfa.models import Citation, Control, EvidenceBackendError, Policy, Rule, sha256

CATALOG = Path(__file__).resolve().parents[1] / "policies" / "ap-v1.json"
DIMENSIONS = 256
WORDS = re.compile(r"[^\W_]+", re.UNICODE)
RelatedSearch = Callable[[Control], list[Citation]]


def load_policy() -> tuple[Policy, str]:
    data = CATALOG.read_bytes()
    policy = Policy.model_validate_json(data)
    if (
        len(policy.controls) != len(Rule)
        or {control.rule for control in policy.controls} != set(Rule)
        or len({control.id for control in policy.controls}) != len(policy.controls)
        or set(policy.approval_thresholds) != {"USD", "EUR", "VND"}
        or any(amount <= 0 for amount in policy.approval_thresholds.values())
    ):
        raise ValueError("The policy catalog has invalid control coverage or thresholds.")
    return policy, sha256(data)


def cite(policy: Policy, control: Control) -> Citation:
    return Citation(
        id=control.id, version=policy.version, title=control.title, clause=control.clause
    )


def _embed(text: str) -> list[float]:
    """Local feature hashing. This demo encoder is lexical and makes no network calls."""
    vector = [0.0] * DIMENSIONS
    for word in set(WORDS.findall(text.casefold())):
        signature = hashlib.blake2b(word.encode("utf-8"), digest_size=4).digest()
        vector[int.from_bytes(signature[:2], "big") % DIMENSIONS] += (
            1.0 if signature[2] % 2 else -1.0
        )
    norm = math.sqrt(sum(number * number for number in vector))
    return [number / norm for number in vector] if norm else vector


def _text(control: Control) -> str:
    return f"{control.title} {control.clause}"


def make_related_search(
    policy: Policy, digest: str, backend: str, state_dir: Path
) -> RelatedSearch:
    vectors = {control.id: _embed(_text(control)) for control in policy.controls}
    by_id = {control.id: control for control in policy.controls}
    if backend == "chroma":
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        from chromadb.errors import ChromaError

        client = chromadb.PersistentClient(
            path=str(state_dir / "chroma"), settings=ChromaSettings(anonymized_telemetry=False)
        )
        collection = client.get_or_create_collection(
            name=f"ap-hash256-v1-{digest[:32]}",
            embedding_function=None,
            configuration={"hnsw": {"space": "cosine"}},
        )
        collection.upsert(
            ids=list(vectors),
            embeddings=list(vectors.values()),
            documents=[_text(control) for control in policy.controls],
            metadatas=[{"version": policy.version} for _ in policy.controls],
        )

        def distances(control: Control) -> list[tuple[str, float]]:
            try:
                result = collection.query(
                    query_embeddings=[vectors[control.id]],
                    n_results=len(vectors),
                    include=["distances"],
                    where={"version": policy.version},
                )
            except (ChromaError, OSError) as exc:
                raise EvidenceBackendError("Chroma retrieval failed.") from exc
            values = result["distances"]
            return list(zip(result["ids"][0], values[0], strict=True)) if values else []
    else:

        def distances(control: Control) -> list[tuple[str, float]]:
            query = vectors[control.id]
            return [
                (key, 1.0 - sum(a * b for a, b in zip(query, vector, strict=True)))
                for key, vector in vectors.items()
            ]

    def search(control: Control) -> list[Citation]:
        ranked = sorted(distances(control), key=lambda match: (round(match[1], 6), match[0]))
        return [
            cite(policy, by_id[key])
            for key, distance in ranked
            if key != control.id and key in by_id and distance < 0.92
        ][:2]

    return search
