"""Replaceable backend contract for approved Catalog retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Protocol, runtime_checkable

from src.catalog.loader import ToolCatalog
from src.catalog.retriever import (
    CATALOG_APPROVED_TRUST_STATUS,
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
    _validate_backend_result(
        result,
        backend_name=backend.name,
        query=query,
        tool_catalog=tool_catalog,
        recipe_catalog=recipe_catalog,
    )
    return result


def _normalize_backend_name(name: str | None) -> str:
    normalized = (name or DEFAULT_RETRIEVAL_BACKEND).strip().lower()
    return normalized or DEFAULT_RETRIEVAL_BACKEND


def _validate_backend_result(
    result: Any,
    *,
    backend_name: str,
    query: str,
    tool_catalog: ToolCatalog,
    recipe_catalog: RecipeCatalog,
) -> None:
    if not isinstance(result, dict):
        raise ValueError(f"Retrieval backend '{backend_name}' must return an object.")
    _validate_json_value(result, backend_name=backend_name)

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

    recipes = _candidate_objects(result, "recipes", backend_name=backend_name)
    for candidate in recipes:
        recipe_id = _validate_common_candidate(
            candidate,
            candidate_kind="recipe",
            backend_name=backend_name,
        )
        try:
            recipe_catalog.get(recipe_id)
        except KeyError as exc:
            raise ValueError(
                f"Retrieval backend '{backend_name}' returned unknown approved recipe "
                f"'{recipe_id}'."
            ) from exc

    tools = _candidate_objects(result, "tools", backend_name=backend_name)
    for candidate in tools:
        tool_id = _validate_common_candidate(
            candidate,
            candidate_kind="tool",
            backend_name=backend_name,
        )
        version = candidate.get("version")
        if not isinstance(version, str) or not version.strip():
            raise ValueError(
                f"Retrieval backend '{backend_name}' tool candidates must define "
                "a non-empty version."
            )
        try:
            tool = tool_catalog.get(tool_id, version)
        except KeyError as exc:
            raise ValueError(
                f"Retrieval backend '{backend_name}' returned unknown approved tool "
                f"version '{tool_id}@{version}'."
            ) from exc
        if candidate.get("trust_status") != CATALOG_APPROVED_TRUST_STATUS:
            raise ValueError(
                f"Retrieval backend '{backend_name}' tool '{tool_id}@{version}' must use "
                f"trust_status '{CATALOG_APPROVED_TRUST_STATUS}'."
            )
        expected_verification = tool.execution_verification.model_dump(mode="json")
        if candidate.get("execution_verification") != expected_verification:
            raise ValueError(
                f"Retrieval backend '{backend_name}' tool '{tool_id}@{version}' must "
                "preserve Catalog execution_verification."
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


def _candidate_objects(
    result: dict[str, Any],
    field_name: str,
    *,
    backend_name: str,
) -> list[dict[str, Any]]:
    candidates = result.get(field_name)
    if not isinstance(candidates, list) or any(
        not isinstance(candidate, dict) for candidate in candidates
    ):
        raise ValueError(
            f"Retrieval backend '{backend_name}' field '{field_name}' "
            "must be a list of objects."
        )
    return candidates


def _validate_common_candidate(
    candidate: dict[str, Any],
    *,
    candidate_kind: str,
    backend_name: str,
) -> str:
    candidate_id = candidate.get("id")
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise ValueError(
            f"Retrieval backend '{backend_name}' {candidate_kind} candidates "
            "must define a non-empty id."
        )

    score = candidate.get("score")
    if not _is_finite_number(score):
        raise ValueError(
            f"Retrieval backend '{backend_name}' {candidate_kind} '{candidate_id}' "
            "must define a finite numeric score."
        )
    for field_name in ("matched_terms", "matched_fields"):
        value = candidate.get(field_name)
        if not isinstance(value, list) or any(
            not isinstance(item, str) for item in value
        ):
            raise ValueError(
                f"Retrieval backend '{backend_name}' {candidate_kind} '{candidate_id}' "
                f"field '{field_name}' must be a list of strings."
            )
    if not isinstance(candidate.get("reason"), str):
        raise ValueError(
            f"Retrieval backend '{backend_name}' {candidate_kind} '{candidate_id}' "
            "must define a string reason."
        )

    candidate_evidence = candidate.get("backend_evidence")
    if candidate_evidence is not None and not isinstance(candidate_evidence, dict):
        raise ValueError(
            f"Retrieval backend '{backend_name}' candidate backend_evidence "
            "must be an object."
        )
    return candidate_id


def _is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and (not isinstance(value, float) or isfinite(value))
    )


def _validate_json_value(
    value: Any,
    *,
    backend_name: str,
    path: str = "$",
    active_containers: set[int] | None = None,
) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError(
                f"Retrieval backend '{backend_name}' returned a non-finite number "
                f"at {path}."
            )
        return

    if not isinstance(value, (list, dict)):
        raise ValueError(
            f"Retrieval backend '{backend_name}' returned a non-JSON-compatible value "
            f"at {path}."
        )

    active_containers = active_containers if active_containers is not None else set()
    container_id = id(value)
    if container_id in active_containers:
        raise ValueError(
            f"Retrieval backend '{backend_name}' returned a circular value at {path}."
        )
    active_containers.add(container_id)
    try:
        if isinstance(value, list):
            for index, item in enumerate(value):
                _validate_json_value(
                    item,
                    backend_name=backend_name,
                    path=f"{path}[{index}]",
                    active_containers=active_containers,
                )
            return

        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError(
                    f"Retrieval backend '{backend_name}' returned a non-string object key "
                    f"at {path}."
                )
            _validate_json_value(
                item,
                backend_name=backend_name,
                path=f"{path}.{key}",
                active_containers=active_containers,
            )
    finally:
        active_containers.remove(container_id)
