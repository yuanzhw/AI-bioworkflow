"""Replaceable backend contract for approved Catalog retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from src.catalog.loader import ToolCatalog
from src.catalog.retriever import (
    LEXICAL_RETRIEVER_STRATEGY,
    retrieve_catalog_context,
    tokenize_for_retrieval,
)
from src.recipes.loader import RecipeCatalog


DEFAULT_RETRIEVAL_BACKEND = LEXICAL_RETRIEVER_STRATEGY
SUPPORTED_RETRIEVAL_BACKENDS = (LEXICAL_RETRIEVER_STRATEGY,)
BACKEND_EVIDENCE_SCHEMA_VERSION = "1.0"


@runtime_checkable
class CatalogRetrievalBackend(Protocol):
    """Retrieve approved recipe and tool candidates behind a stable contract."""

    name: str

    def retrieve(
        self,
        query: str,
        tool_catalog: ToolCatalog,
        recipe_catalog: RecipeCatalog,
        top_k_recipes: int = 3,
        top_k_tools: int = 8,
    ) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class LexicalCatalogRetrievalBackend:
    """Adapter that exposes the existing deterministic lexical retriever."""

    name: str = LEXICAL_RETRIEVER_STRATEGY

    def retrieve(
        self,
        query: str,
        tool_catalog: ToolCatalog,
        recipe_catalog: RecipeCatalog,
        top_k_recipes: int = 3,
        top_k_tools: int = 8,
    ) -> dict[str, Any]:
        result = retrieve_catalog_context(
            query,
            tool_catalog,
            recipe_catalog,
            top_k_recipes,
            top_k_tools,
        )
        return {
            **result,
            "backend_evidence": {
                "schema_version": BACKEND_EVIDENCE_SCHEMA_VERSION,
                "backend": self.name,
                "query_tokens": tokenize_for_retrieval(query.strip()),
            },
        }


def get_catalog_retrieval_backend(
    name: str | None = None,
) -> CatalogRetrievalBackend:
    """Return an explicitly selected approved Catalog retrieval backend."""
    selected = _normalize_backend_name(name)
    if selected == LEXICAL_RETRIEVER_STRATEGY:
        return LexicalCatalogRetrievalBackend()
    raise ValueError(
        f"Unknown Catalog retrieval backend '{selected}'. Supported backends: "
        f"{', '.join(SUPPORTED_RETRIEVAL_BACKENDS)}."
    )


def retrieve_catalog_context_with_backend(
    backend: CatalogRetrievalBackend,
    query: str,
    tool_catalog: ToolCatalog,
    recipe_catalog: RecipeCatalog,
    top_k_recipes: int = 3,
    top_k_tools: int = 8,
) -> dict[str, Any]:
    """Run a backend and validate the common JSON-ready artifact contract."""
    result = backend.retrieve(
        query,
        tool_catalog,
        recipe_catalog,
        top_k_recipes,
        top_k_tools,
    )
    _validate_backend_result(result, backend_name=backend.name, query=query)
    return result


def _normalize_backend_name(name: str | None) -> str:
    normalized = (name or DEFAULT_RETRIEVAL_BACKEND).strip().lower()
    return normalized or DEFAULT_RETRIEVAL_BACKEND


def _validate_backend_result(
    result: dict[str, Any],
    *,
    backend_name: str,
    query: str,
) -> None:
    if not isinstance(result, dict):
        raise ValueError(f"Retrieval backend '{backend_name}' must return an object.")

    normalized_query = query.strip()
    if result.get("query") != normalized_query:
        raise ValueError(
            f"Retrieval backend '{backend_name}' must preserve the normalized query."
        )
    if result.get("strategy") != backend_name:
        raise ValueError(
            f"Retrieval backend '{backend_name}' returned strategy "
            f"{result.get('strategy')!r}."
        )

    for field_name in ("recipes", "tools"):
        candidates = result.get(field_name)
        if not isinstance(candidates, list) or any(
            not isinstance(candidate, dict) for candidate in candidates
        ):
            raise ValueError(
                f"Retrieval backend '{backend_name}' field '{field_name}' "
                "must be a list of objects."
            )
        for candidate in candidates:
            if not isinstance(candidate.get("id"), str) or not candidate["id"].strip():
                raise ValueError(
                    f"Retrieval backend '{backend_name}' {field_name} candidates "
                    "must define a non-empty id."
                )
            candidate_evidence = candidate.get("backend_evidence")
            if candidate_evidence is not None and not isinstance(candidate_evidence, dict):
                raise ValueError(
                    f"Retrieval backend '{backend_name}' candidate backend_evidence "
                    "must be an object."
                )

    fallback_values: dict[str, bool] = {}
    for field_name in (
        "recipe_fallback_used",
        "tool_fallback_used",
        "fallback_used",
    ):
        value = result.get(field_name)
        if not isinstance(value, bool):
            raise ValueError(
                f"Retrieval backend '{backend_name}' field '{field_name}' "
                "must be a boolean."
            )
        fallback_values[field_name] = value

    expected_fallback = (
        fallback_values["recipe_fallback_used"]
        or fallback_values["tool_fallback_used"]
    )
    if fallback_values["fallback_used"] != expected_fallback:
        raise ValueError(
            f"Retrieval backend '{backend_name}' fallback_used must equal "
            "recipe_fallback_used or tool_fallback_used."
        )

    fallback_reason = result.get("fallback_reason")
    if fallback_reason is not None and not isinstance(fallback_reason, str):
        raise ValueError(
            f"Retrieval backend '{backend_name}' fallback_reason must be a string or null."
        )

    evidence = result.get("backend_evidence")
    if not isinstance(evidence, dict):
        raise ValueError(
            f"Retrieval backend '{backend_name}' must return backend_evidence."
        )
    if evidence.get("schema_version") != BACKEND_EVIDENCE_SCHEMA_VERSION:
        raise ValueError(
            f"Retrieval backend '{backend_name}' backend_evidence must use schema version "
            f"{BACKEND_EVIDENCE_SCHEMA_VERSION}."
        )
    if evidence.get("backend") != backend_name:
        raise ValueError(
            f"Retrieval backend '{backend_name}' backend_evidence must identify the backend."
        )
