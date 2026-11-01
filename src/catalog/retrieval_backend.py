"""Replaceable backend contract for approved Catalog retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any, Protocol, runtime_checkable

from src.catalog.loader import ToolCatalog
from src.catalog.retrieval_documents import (CatalogRetrievalDocument,
                                             build_catalog_retrieval_corpus)
from src.catalog.retriever import (CATALOG_APPROVED_TRUST_STATUS,
                                   LEXICAL_RETRIEVER_STRATEGY,
                                   retrieve_catalog_context,
                                   tokenize_for_retrieval)
from src.catalog.vector_retrieval import (VECTOR_RETRIEVER_STRATEGY,
                                          VECTOR_SCORE_PRECISION,
                                          CatalogVectorIndex,
                                          CatalogVectorSearchResult,
                                          EmbeddingProvider,
                                          LocalEmbeddingModelConfig,
                                          SentenceTransformerEmbeddingProvider,
                                          build_catalog_vector_index,
                                          embed_catalog_query,
                                          search_catalog_vector_index)
from src.recipes.loader import RecipeCatalog

DEFAULT_RETRIEVAL_BACKEND = LEXICAL_RETRIEVER_STRATEGY
SUPPORTED_RETRIEVAL_BACKENDS = (
    LEXICAL_RETRIEVER_STRATEGY,
    VECTOR_RETRIEVER_STRATEGY,
)
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


class VectorCatalogRetrievalBackend:
    """Exact cosine retrieval over one pinned local embedding model and corpus."""

    name = VECTOR_RETRIEVER_STRATEGY

    def __init__(
        self,
        provider: EmbeddingProvider,
        tool_catalog: ToolCatalog,
        recipe_catalog: RecipeCatalog,
    ):
        corpus = build_catalog_retrieval_corpus(tool_catalog, recipe_catalog)
        self._provider = provider
        self._corpus = corpus
        self._index = build_catalog_vector_index(corpus, provider)
        self._documents_by_id = {
            document.document_id: document for document in corpus.documents
        }

    @property
    def index(self) -> CatalogVectorIndex:
        return self._index

    def retrieve(
        self,
        query: str,
        tool_catalog: ToolCatalog,
        recipe_catalog: RecipeCatalog,
        top_k_recipes: int = 3,
        top_k_tools: int = 8,
    ) -> dict[str, Any]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query must not be empty")
        _validate_top_k("top_k_recipes", top_k_recipes)
        _validate_top_k("top_k_tools", top_k_tools)

        current_corpus = build_catalog_retrieval_corpus(
            tool_catalog,
            recipe_catalog,
        )
        if current_corpus.fingerprint != self._corpus.fingerprint:
            raise ValueError(
                "vector_v1 index corpus fingerprint does not match the current Catalog"
            )

        query_vector = embed_catalog_query(normalized_query, self._provider)
        recipe_matches = search_catalog_vector_index(
            self._index,
            query_vector,
            kind="recipe",
            top_k=top_k_recipes,
        )
        tool_matches = search_catalog_vector_index(
            self._index,
            query_vector,
            kind="tool",
            top_k=top_k_tools,
        )

        return {
            "query": normalized_query,
            "strategy": self.name,
            "recipes": [
                self._recipe_result(match, rank=rank)
                for rank, match in enumerate(recipe_matches, start=1)
            ],
            "tools": [
                self._tool_result(
                    match,
                    rank=rank,
                    tool_catalog=tool_catalog,
                )
                for rank, match in enumerate(tool_matches, start=1)
            ],
            "recipe_fallback_used": False,
            "tool_fallback_used": False,
            "fallback_used": False,
            "fallback_reason": None,
            "backend_evidence": self._backend_evidence(),
        }

    def _recipe_result(
        self,
        match: CatalogVectorSearchResult,
        *,
        rank: int,
    ) -> dict[str, Any]:
        document = self._document(match)
        score = _json_similarity(match.score)
        return {
            "id": document.catalog_id,
            "score": score,
            "matched_terms": [],
            "matched_fields": [],
            "reason": "Ranked by exact cosine similarity over the approved Catalog corpus.",
            "backend_evidence": {
                "document_id": document.document_id,
                "rank": rank,
                "cosine_similarity": score,
            },
        }

    def _tool_result(
        self,
        match: CatalogVectorSearchResult,
        *,
        rank: int,
        tool_catalog: ToolCatalog,
    ) -> dict[str, Any]:
        document = self._document(match)
        version = document.catalog_version
        if version is None:
            raise ValueError(
                f"vector tool document '{document.document_id}' has no version"
            )
        tool = tool_catalog.get(document.catalog_id, version)
        score = _json_similarity(match.score)
        return {
            "id": tool.id,
            "version": tool.version,
            "score": score,
            "matched_terms": [],
            "matched_fields": [],
            "trust_status": CATALOG_APPROVED_TRUST_STATUS,
            "execution_verification": tool.execution_verification.model_dump(mode="json"),
            "reason": "Ranked by exact cosine similarity over the approved Catalog corpus.",
            "backend_evidence": {
                "document_id": document.document_id,
                "rank": rank,
                "cosine_similarity": score,
            },
        }

    def _document(
        self,
        match: CatalogVectorSearchResult,
    ) -> CatalogRetrievalDocument:
        try:
            return self._documents_by_id[match.entry.document_id]
        except KeyError as exc:
            raise ValueError(
                f"vector index returned unknown document '{match.entry.document_id}'"
            ) from exc

    def _backend_evidence(self) -> dict[str, Any]:
        return {
            "schema_version": BACKEND_EVIDENCE_SCHEMA_VERSION,
            "backend": self.name,
            "model_id": self._index.model_id,
            "model_revision": self._index.model_revision,
            "embedding_dimension": self._index.dimension,
            "query_prefix": self._index.query_prefix,
            "document_prefix": self._index.document_prefix,
            "document_schema_version": self._index.document_schema_version,
            "corpus_fingerprint": self._index.corpus_fingerprint,
            "index_schema_version": self._index.schema_version,
            "index_fingerprint": self._index.fingerprint,
            "similarity": "cosine",
        }


def get_catalog_retrieval_backend(
    name: str | None = None,
    *,
    vector_config: LocalEmbeddingModelConfig | None = None,
    embedding_provider: EmbeddingProvider | None = None,
    tool_catalog: ToolCatalog | None = None,
    recipe_catalog: RecipeCatalog | None = None,
) -> CatalogRetrievalBackend:
    """Return an explicitly selected approved Catalog retrieval backend."""
    selected = _normalize_backend_name(name)
    if selected == LEXICAL_RETRIEVER_STRATEGY:
        if vector_config is not None or embedding_provider is not None:
            raise ValueError("vector configuration requires backend 'vector_v1'")
        return LexicalCatalogRetrievalBackend()
    if selected == VECTOR_RETRIEVER_STRATEGY:
        if tool_catalog is None or recipe_catalog is None:
            raise ValueError(
                "vector_v1 requires explicit Tool Catalog and Recipe Catalog instances"
            )
        if vector_config is not None and embedding_provider is not None:
            raise ValueError(
                "vector_v1 accepts either vector_config or embedding_provider, not both"
            )
        provider = embedding_provider
        if provider is None:
            if vector_config is None:
                raise ValueError(
                    "vector_v1 requires an explicit local embedding model path"
                )
            provider = SentenceTransformerEmbeddingProvider(vector_config)
        return VectorCatalogRetrievalBackend(
            provider,
            tool_catalog,
            recipe_catalog,
        )
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
    backend_name = _validate_backend_name(getattr(backend, "name", None))
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("query must not be empty")
    _validate_top_k("top_k_recipes", top_k_recipes)
    _validate_top_k("top_k_tools", top_k_tools)
    result = backend.retrieve(
        normalized_query,
        tool_catalog,
        recipe_catalog,
        top_k_recipes,
        top_k_tools,
    )
    _validate_backend_result(
        result,
        backend_name=backend_name,
        query=normalized_query,
        tool_catalog=tool_catalog,
        recipe_catalog=recipe_catalog,
        top_k_recipes=top_k_recipes,
        top_k_tools=top_k_tools,
    )
    return result


def _normalize_backend_name(name: str | None) -> str:
    normalized = (name or DEFAULT_RETRIEVAL_BACKEND).strip().lower()
    return normalized or DEFAULT_RETRIEVAL_BACKEND


def _validate_backend_name(name: Any) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("Retrieval backend name must be a non-empty string.")
    return name


def _validate_backend_result(
    result: Any,
    *,
    backend_name: str,
    query: str,
    tool_catalog: ToolCatalog,
    recipe_catalog: RecipeCatalog,
    top_k_recipes: int,
    top_k_tools: int,
) -> None:
    if not isinstance(result, dict):
        raise ValueError(f"Retrieval backend '{backend_name}' must return an object.")
    _validate_json_value(result, backend_name=backend_name)

    if result.get("query") != query:
        raise ValueError(
            f"Retrieval backend '{backend_name}' must preserve the normalized query."
        )
    if result.get("strategy") != backend_name:
        raise ValueError(
            f"Retrieval backend '{backend_name}' returned strategy "
            f"{result.get('strategy')!r}."
        )

    recipes = _candidate_objects(
        result,
        "recipes",
        backend_name=backend_name,
        maximum_count=top_k_recipes,
        limit_name="top_k_recipes",
    )
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

    tools = _candidate_objects(
        result,
        "tools",
        backend_name=backend_name,
        maximum_count=top_k_tools,
        limit_name="top_k_tools",
    )
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
    if expected_fallback and (
        not isinstance(fallback_reason, str) or not fallback_reason.strip()
    ):
        raise ValueError(
            f"Retrieval backend '{backend_name}' fallback_reason must be a non-empty "
            "string when fallback_used is true."
        )
    if not expected_fallback and fallback_reason is not None:
        raise ValueError(
            f"Retrieval backend '{backend_name}' fallback_reason must be null when "
            "fallback_used is false."
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
    maximum_count: int,
    limit_name: str,
) -> list[dict[str, Any]]:
    candidates = result.get(field_name)
    if not isinstance(candidates, list) or any(
        not isinstance(candidate, dict) for candidate in candidates
    ):
        raise ValueError(
            f"Retrieval backend '{backend_name}' field '{field_name}' "
            "must be a list of objects."
        )
    if len(candidates) > maximum_count:
        raise ValueError(
            f"Retrieval backend '{backend_name}' field '{field_name}' returned "
            f"{len(candidates)} candidates, exceeding {limit_name}={maximum_count}."
        )
    return candidates


def _validate_top_k(field_name: str, value: Any) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")


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


def _json_similarity(score: float) -> float:
    rounded = round(score, VECTOR_SCORE_PRECISION)
    return 0.0 if rounded == 0.0 else rounded


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
