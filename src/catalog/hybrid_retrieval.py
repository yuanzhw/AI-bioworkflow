"""Deterministic reciprocal-rank fusion for Catalog retrieval candidates."""

from __future__ import annotations

from typing import Any, Literal

from src.catalog.retriever import LEXICAL_RETRIEVER_STRATEGY
from src.catalog.vector_retrieval import VECTOR_RETRIEVER_STRATEGY

HYBRID_RETRIEVER_STRATEGY = "hybrid_v1"
HYBRID_FUSION_ALGORITHM = "reciprocal_rank_fusion"
DEFAULT_RRF_K = 60
HYBRID_SCORE_PRECISION = 12

_CandidateKind = Literal["recipe", "tool"]


def fuse_catalog_candidate_ranks(
    lexical_candidates: list[dict[str, Any]],
    vector_candidates: list[dict[str, Any]],
    *,
    candidate_kind: _CandidateKind,
    rrf_k: int = DEFAULT_RRF_K,
) -> list[dict[str, Any]]:
    """Fuse direct lexical/vector rankings without mixing their score scales."""
    _validate_rrf_k(rrf_k)
    if candidate_kind not in ("recipe", "tool"):
        raise ValueError("candidate_kind must be 'recipe' or 'tool'")

    ranked: dict[tuple[str, ...], dict[str, Any]] = {}
    for backend_name, candidates in (
        (LEXICAL_RETRIEVER_STRATEGY, lexical_candidates),
        (VECTOR_RETRIEVER_STRATEGY, vector_candidates),
    ):
        for rank, candidate in enumerate(candidates, start=1):
            identity = _candidate_identity(candidate, candidate_kind=candidate_kind)
            record = ranked.setdefault(
                identity,
                {
                    "score": 0.0,
                    "components": {},
                },
            )
            if backend_name in record["components"]:
                raise ValueError(
                    f"{backend_name} returned duplicate hybrid candidate {identity!r}"
                )
            contribution = 1.0 / (rrf_k + rank)
            record["score"] += contribution
            record["components"][backend_name] = {
                "rank": rank,
                "score": candidate["score"],
                "rrf_contribution": _json_fusion_score(contribution),
                "candidate_evidence": candidate.get("backend_evidence"),
                "candidate": candidate,
            }

    ordered = sorted(
        ranked.items(),
        key=lambda item: (-item[1]["score"], item[0]),
    )
    return [
        _fused_candidate(
            identity,
            record,
            candidate_kind=candidate_kind,
            rrf_k=rrf_k,
        )
        for identity, record in ordered
    ]


def build_hybrid_fallback_candidates(
    candidates: list[dict[str, Any]],
    *,
    candidate_kind: _CandidateKind,
    component_backend: Literal["lexical_v1", "vector_v1"],
    rrf_k: int = DEFAULT_RRF_K,
) -> list[dict[str, Any]]:
    """Preserve deterministic component fallback candidates without RRF credit."""
    _validate_rrf_k(rrf_k)
    if candidate_kind not in ("recipe", "tool"):
        raise ValueError("candidate_kind must be 'recipe' or 'tool'")
    if component_backend not in (
        LEXICAL_RETRIEVER_STRATEGY,
        VECTOR_RETRIEVER_STRATEGY,
    ):
        raise ValueError("component_backend must be 'lexical_v1' or 'vector_v1'")

    fallback: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for rank, candidate in enumerate(candidates, start=1):
        identity = _candidate_identity(candidate, candidate_kind=candidate_kind)
        if identity in seen:
            raise ValueError(
                f"{component_backend} returned duplicate fallback candidate {identity!r}"
            )
        seen.add(identity)
        result = {
            "id": candidate["id"],
            "score": 0.0,
            "matched_terms": [],
            "matched_fields": [],
            "reason": "Fallback result after all hybrid ranking components returned fallback.",
            "backend_evidence": {
                "fusion": {
                    "algorithm": HYBRID_FUSION_ALGORITHM,
                    "rrf_k": rrf_k,
                    "score": 0.0,
                    "fallback": True,
                },
                "components": {
                    LEXICAL_RETRIEVER_STRATEGY: (
                        _fallback_component_evidence(rank, candidate)
                        if component_backend == LEXICAL_RETRIEVER_STRATEGY
                        else None
                    ),
                    VECTOR_RETRIEVER_STRATEGY: (
                        _fallback_component_evidence(rank, candidate)
                        if component_backend == VECTOR_RETRIEVER_STRATEGY
                        else None
                    ),
                },
            },
        }
        if candidate_kind == "tool":
            result.update(
                {
                    "version": candidate["version"],
                    "trust_status": candidate["trust_status"],
                    "execution_verification": candidate["execution_verification"],
                }
            )
        fallback.append(result)
    return fallback


def _fused_candidate(
    identity: tuple[str, ...],
    record: dict[str, Any],
    *,
    candidate_kind: _CandidateKind,
    rrf_k: int,
) -> dict[str, Any]:
    components = record["components"]
    lexical = components.get(LEXICAL_RETRIEVER_STRATEGY)
    vector = components.get(VECTOR_RETRIEVER_STRATEGY)
    source = lexical or vector
    if source is None:
        raise ValueError(f"hybrid candidate {identity!r} has no ranking component")

    lexical_candidate = lexical["candidate"] if lexical is not None else None
    source_candidate = source["candidate"]
    fusion_score = _json_fusion_score(record["score"])
    result = {
        "id": source_candidate["id"],
        "score": fusion_score,
        "matched_terms": (
            list(lexical_candidate["matched_terms"])
            if lexical_candidate is not None
            else []
        ),
        "matched_fields": (
            list(lexical_candidate["matched_fields"])
            if lexical_candidate is not None
            else []
        ),
        "reason": (
            "Fused lexical and vector ranks over the approved Catalog with "
            "reciprocal rank fusion."
        ),
        "backend_evidence": {
            "fusion": {
                "algorithm": HYBRID_FUSION_ALGORITHM,
                "rrf_k": rrf_k,
                "score": fusion_score,
                "fallback": False,
            },
            "components": {
                LEXICAL_RETRIEVER_STRATEGY: _component_evidence(lexical),
                VECTOR_RETRIEVER_STRATEGY: _component_evidence(vector),
            },
        },
    }
    if candidate_kind == "tool":
        result.update(
            {
                "version": source_candidate["version"],
                "trust_status": source_candidate["trust_status"],
                "execution_verification": source_candidate["execution_verification"],
            }
        )
    return result


def _component_evidence(component: dict[str, Any] | None) -> dict[str, Any] | None:
    if component is None:
        return None
    return {
        "rank": component["rank"],
        "score": component["score"],
        "rrf_contribution": component["rrf_contribution"],
        "candidate_evidence": component["candidate_evidence"],
    }


def _fallback_component_evidence(
    rank: int,
    candidate: dict[str, Any],
) -> dict[str, Any]:
    return {
        "rank": rank,
        "score": candidate["score"],
        "rrf_contribution": 0.0,
        "candidate_evidence": candidate.get("backend_evidence"),
    }


def _candidate_identity(
    candidate: dict[str, Any],
    *,
    candidate_kind: _CandidateKind,
) -> tuple[str, ...]:
    candidate_id = candidate.get("id")
    if not isinstance(candidate_id, str) or not candidate_id:
        raise ValueError("hybrid candidates must define a non-empty id")
    if candidate_kind == "recipe":
        return (candidate_id,)

    version = candidate.get("version")
    if not isinstance(version, str) or not version:
        raise ValueError("hybrid tool candidates must define a non-empty version")
    return candidate_id, version


def _validate_rrf_k(value: Any) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("rrf_k must be a positive integer")


def _json_fusion_score(score: float) -> float:
    rounded = round(score, HYBRID_SCORE_PRECISION)
    return 0.0 if rounded == 0.0 else rounded
