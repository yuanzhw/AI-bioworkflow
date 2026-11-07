"""Reproducible local embeddings and exact vector search for Catalog documents."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from math import isclose, isfinite, sqrt
from numbers import Real
from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import (BaseModel, ConfigDict, Field, field_validator,
                      model_validator)

from src.catalog.retrieval_documents import (CatalogRetrievalCorpus,
                                             CatalogRetrievalDocumentKind)

VECTOR_RETRIEVER_STRATEGY = "vector_v1"
VECTOR_INDEX_SCHEMA_VERSION = "1.0"
VECTOR_INDEX_FINGERPRINT_ALGORITHM = "sha256"
VECTOR_COMPONENT_PRECISION = 8
VECTOR_SCORE_PRECISION = 6

DEFAULT_EMBEDDING_MODEL_ID = "intfloat/multilingual-e5-small"
DEFAULT_EMBEDDING_MODEL_REVISION = (
    "fd1525a9fd15316a2d503bf26ab031a61d056e98"
)
DEFAULT_EMBEDDING_DIMENSION = 384
DEFAULT_QUERY_PREFIX = "query: "
DEFAULT_DOCUMENT_PREFIX = "passage: "

EMBEDDING_MODEL_MANIFEST_SCHEMA_VERSION = "1.1"
EMBEDDING_MODEL_MANIFEST_FILENAME = "ai-bioworkflow-embedding-model.json"
EMBEDDING_MODEL_REQUIRED_FILES = (
    "1_Pooling/config.json",
    "config.json",
    "model.safetensors",
    "modules.json",
    "sentence_bert_config.json",
    "sentencepiece.bpe.model",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
)
EMBEDDING_MODEL_REJECTED_FILES = ("config_sentence_transformers.json",)


class EmbeddingModelFileDigest(BaseModel):
    """SHA-256 identity for one file required by the local embedding runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EmbeddingModelManifest(BaseModel):
    """Auditable identity written beside an explicitly prepared local model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.1"] = EMBEDDING_MODEL_MANIFEST_SCHEMA_VERSION
    model_id: str
    revision: str
    dimension: int
    query_prefix: str
    document_prefix: str
    files: tuple[EmbeddingModelFileDigest, ...]

    @model_validator(mode="after")
    def validate_supported_model(self):
        _validate_selected_model_identity(
            model_id=self.model_id,
            revision=self.revision,
            dimension=self.dimension,
            query_prefix=self.query_prefix,
            document_prefix=self.document_prefix,
        )
        file_paths = tuple(file.path for file in self.files)
        if file_paths != EMBEDDING_MODEL_REQUIRED_FILES:
            raise ValueError(
                "embedding model manifest files must match the pinned runtime files"
            )
        return self


class LocalEmbeddingModelConfig(BaseModel):
    """Explicit local-only runtime configuration for the selected embedding model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_path: Path
    model_id: str = DEFAULT_EMBEDDING_MODEL_ID
    revision: str = DEFAULT_EMBEDDING_MODEL_REVISION
    dimension: int = DEFAULT_EMBEDDING_DIMENSION
    query_prefix: str = DEFAULT_QUERY_PREFIX
    document_prefix: str = DEFAULT_DOCUMENT_PREFIX
    device: str = "cpu"

    @field_validator("device")
    @classmethod
    def validate_device(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("embedding device must not be empty")
        return normalized

    @model_validator(mode="after")
    def validate_supported_model(self):
        _validate_selected_model_identity(
            model_id=self.model_id,
            revision=self.revision,
            dimension=self.dimension,
            query_prefix=self.query_prefix,
            document_prefix=self.document_prefix,
        )
        return self


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Model-neutral embedding interface used by the exact vector index."""

    model_id: str
    revision: str
    dimension: int
    query_prefix: str
    document_prefix: str

    def embed_queries(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        ...

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        ...


class SentenceTransformerEmbeddingProvider:
    """Load the pinned E5 model from an explicitly prepared local directory."""

    def __init__(self, config: LocalEmbeddingModelConfig):
        model_path = config.model_path.expanduser().resolve()
        manifest = load_embedding_model_manifest(model_path)
        verify_embedding_model_files(model_path, manifest)

        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError(
                "vector_v1 requires the optional vector dependencies; run "
                "'uv sync --extra vector'"
            ) from exc

        try:
            model = SentenceTransformer(
                str(model_path),
                device=config.device,
                local_files_only=True,
                trust_remote_code=False,
            )
        except Exception as exc:
            raise RuntimeError(
                "failed to load the explicitly configured local embedding model"
            ) from exc

        loaded_dimension = model.get_embedding_dimension()
        if loaded_dimension != config.dimension:
            raise ValueError(
                "local embedding model dimension does not match the pinned "
                f"dimension {config.dimension}"
            )

        self.model_id = config.model_id
        self.revision = config.revision
        self.dimension = config.dimension
        self.query_prefix = config.query_prefix
        self.document_prefix = config.document_prefix
        self._model = model

    def embed_queries(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return self._encode(texts, prefix=self.query_prefix)

    def embed_documents(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        return self._encode(texts, prefix=self.document_prefix)

    def _encode(
        self,
        texts: Sequence[str],
        *,
        prefix: str,
    ) -> Sequence[Sequence[float]]:
        if not texts:
            return []
        encoded = self._model.encode(
            [prefix + text for text in texts],
            convert_to_numpy=True,
            normalize_embeddings=False,
            show_progress_bar=False,
        )
        return encoded.tolist()


class CatalogVectorIndexEntry(BaseModel):
    """One normalized vector bound to a canonical Catalog document identity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    kind: CatalogRetrievalDocumentKind
    vector: tuple[float, ...]

    @field_validator("document_id")
    @classmethod
    def validate_document_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("vector index document_id must not be empty")
        return normalized

    @field_validator("vector")
    @classmethod
    def validate_vector_values(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if not value:
            raise ValueError("vector index entries must contain a vector")
        if any(not isfinite(component) for component in value):
            raise ValueError("vector index components must be finite")
        return value

    @model_validator(mode="after")
    def validate_document_identity(self):
        if not self.document_id.startswith(f"{self.kind}:"):
            raise ValueError(
                "vector index document_id prefix must match the document kind"
            )
        return self


class CatalogVectorIndex(BaseModel):
    """Canonical exact-search index derived from one retrieval corpus and model."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = VECTOR_INDEX_SCHEMA_VERSION
    fingerprint_algorithm: Literal["sha256"] = VECTOR_INDEX_FINGERPRINT_ALGORITHM
    fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    model_id: str
    model_revision: str
    dimension: int
    query_prefix: str
    document_prefix: str
    vector_component_precision: int = VECTOR_COMPONENT_PRECISION
    document_schema_version: str
    corpus_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    entries: tuple[CatalogVectorIndexEntry, ...]

    @model_validator(mode="after")
    def validate_entries_and_fingerprint(self):
        _validate_selected_model_identity(
            model_id=self.model_id,
            revision=self.model_revision,
            dimension=self.dimension,
            query_prefix=self.query_prefix,
            document_prefix=self.document_prefix,
        )
        if self.vector_component_precision != VECTOR_COMPONENT_PRECISION:
            raise ValueError(
                "vector index component precision does not match vector_v1"
            )

        document_ids = [entry.document_id for entry in self.entries]
        if not document_ids:
            raise ValueError("vector index must contain at least one entry")
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("vector index document ids must be unique")
        if document_ids != sorted(document_ids):
            raise ValueError("vector index entries must be sorted by document_id")

        for entry in self.entries:
            if len(entry.vector) != self.dimension:
                raise ValueError(
                    f"vector index entry '{entry.document_id}' must have dimension "
                    f"{self.dimension}"
                )
            norm = sqrt(sum(component * component for component in entry.vector))
            if not isclose(norm, 1.0, rel_tol=0.0, abs_tol=1e-5):
                raise ValueError(
                    f"vector index entry '{entry.document_id}' must be normalized"
                )

        expected_fingerprint = fingerprint_catalog_vector_index(
            model_id=self.model_id,
            model_revision=self.model_revision,
            dimension=self.dimension,
            query_prefix=self.query_prefix,
            document_prefix=self.document_prefix,
            document_schema_version=self.document_schema_version,
            corpus_fingerprint=self.corpus_fingerprint,
            entries=self.entries,
        )
        if self.fingerprint != expected_fingerprint:
            raise ValueError(
                "vector index fingerprint must match its canonical entries and metadata"
            )
        return self


@dataclass(frozen=True)
class CatalogVectorSearchResult:
    entry: CatalogVectorIndexEntry
    score: float


def embedding_model_manifest(model_path: Path) -> EmbeddingModelManifest:
    """Build the pinned model manifest from the prepared runtime files."""
    resolved_model_path = model_path.expanduser().resolve()
    _reject_unmanifested_embedding_model_files(resolved_model_path)
    return EmbeddingModelManifest(
        model_id=DEFAULT_EMBEDDING_MODEL_ID,
        revision=DEFAULT_EMBEDDING_MODEL_REVISION,
        dimension=DEFAULT_EMBEDDING_DIMENSION,
        query_prefix=DEFAULT_QUERY_PREFIX,
        document_prefix=DEFAULT_DOCUMENT_PREFIX,
        files=tuple(
            EmbeddingModelFileDigest(
                path=relative_path,
                sha256=_sha256_embedding_model_file(
                    resolved_model_path,
                    relative_path,
                ),
            )
            for relative_path in EMBEDDING_MODEL_REQUIRED_FILES
        ),
    )


def load_embedding_model_manifest(model_path: Path) -> EmbeddingModelManifest:
    """Load and validate the local model manifest without network access."""
    if not model_path.is_dir():
        raise ValueError("embedding model path must be an existing directory")
    manifest_path = model_path / EMBEDDING_MODEL_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ValueError(
            f"embedding model path must contain {EMBEDDING_MODEL_MANIFEST_FILENAME}"
        )
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        return EmbeddingModelManifest.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError("embedding model manifest is invalid") from exc


def verify_embedding_model_files(
    model_path: Path,
    manifest: EmbeddingModelManifest,
) -> None:
    """Verify prepared model files before importing the embedding runtime."""
    resolved_model_path = model_path.expanduser().resolve()
    _reject_unmanifested_embedding_model_files(resolved_model_path)
    for file in manifest.files:
        actual_sha256 = _sha256_embedding_model_file(
            resolved_model_path,
            file.path,
        )
        if actual_sha256 != file.sha256:
            raise ValueError(
                f"embedding model file digest mismatch for '{file.path}'"
            )


def _reject_unmanifested_embedding_model_files(model_path: Path) -> None:
    for relative_path in EMBEDDING_MODEL_REJECTED_FILES:
        if (model_path / relative_path).exists():
            raise ValueError(
                "embedding model snapshot contains unmanifested runtime file "
                f"'{relative_path}'"
            )


def _sha256_embedding_model_file(model_path: Path, relative_path: str) -> str:
    file_path = model_path / relative_path
    if not file_path.is_file():
        raise ValueError(
            f"embedding model snapshot is missing required file '{relative_path}'"
        )
    try:
        with file_path.open("rb") as handle:
            return hashlib.file_digest(handle, "sha256").hexdigest()
    except OSError as exc:
        raise ValueError(
            f"embedding model file '{relative_path}' could not be read"
        ) from exc


def build_catalog_vector_index(
    corpus: CatalogRetrievalCorpus,
    provider: EmbeddingProvider,
) -> CatalogVectorIndex:
    """Embed the canonical corpus once and build a deterministic exact-search index."""
    _validate_provider(provider)
    raw_vectors = provider.embed_documents(
        [document.text for document in corpus.documents]
    )
    vectors = _normalize_embedding_batch(
        raw_vectors,
        expected_count=len(corpus.documents),
        dimension=provider.dimension,
        label="document embeddings",
    )
    entries = tuple(
        CatalogVectorIndexEntry(
            document_id=document.document_id,
            kind=document.kind,
            vector=vector,
        )
        for document, vector in zip(corpus.documents, vectors, strict=True)
    )
    fingerprint = fingerprint_catalog_vector_index(
        model_id=provider.model_id,
        model_revision=provider.revision,
        dimension=provider.dimension,
        query_prefix=provider.query_prefix,
        document_prefix=provider.document_prefix,
        document_schema_version=corpus.document_schema_version,
        corpus_fingerprint=corpus.fingerprint,
        entries=entries,
    )
    return CatalogVectorIndex(
        fingerprint=fingerprint,
        model_id=provider.model_id,
        model_revision=provider.revision,
        dimension=provider.dimension,
        query_prefix=provider.query_prefix,
        document_prefix=provider.document_prefix,
        document_schema_version=corpus.document_schema_version,
        corpus_fingerprint=corpus.fingerprint,
        entries=entries,
    )


def embed_catalog_query(
    query: str,
    provider: EmbeddingProvider,
) -> tuple[float, ...]:
    """Embed and normalize one query using the same pinned vector contract."""
    _validate_provider(provider)
    vectors = _normalize_embedding_batch(
        provider.embed_queries([query]),
        expected_count=1,
        dimension=provider.dimension,
        label="query embeddings",
    )
    return vectors[0]


def search_catalog_vector_index(
    index: CatalogVectorIndex,
    query_vector: Sequence[float],
    *,
    kind: CatalogRetrievalDocumentKind,
    top_k: int,
) -> list[CatalogVectorSearchResult]:
    """Return exact cosine results with deterministic document-id tie breaking."""
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k < 1:
        raise ValueError("vector search top_k must be a positive integer")
    normalized_query = _normalize_embedding(
        query_vector,
        dimension=index.dimension,
        label="query embedding",
    )
    scored = [
        CatalogVectorSearchResult(
            entry=entry,
            score=sum(
                query_component * document_component
                for query_component, document_component in zip(
                    normalized_query,
                    entry.vector,
                    strict=True,
                )
            ),
        )
        for entry in index.entries
        if entry.kind == kind
    ]
    return sorted(
        scored,
        key=lambda result: (-result.score, result.entry.document_id),
    )[:top_k]


def fingerprint_catalog_vector_index(
    *,
    model_id: str,
    model_revision: str,
    dimension: int,
    query_prefix: str,
    document_prefix: str,
    document_schema_version: str,
    corpus_fingerprint: str,
    entries: Sequence[CatalogVectorIndexEntry],
) -> str:
    """Hash canonical model, corpus, and quantized vector content."""
    payload = {
        "schema_version": VECTOR_INDEX_SCHEMA_VERSION,
        "model_id": model_id,
        "model_revision": model_revision,
        "dimension": dimension,
        "query_prefix": query_prefix,
        "document_prefix": document_prefix,
        "vector_component_precision": VECTOR_COMPONENT_PRECISION,
        "document_schema_version": document_schema_version,
        "corpus_fingerprint": corpus_fingerprint,
        "entries": [entry.model_dump(mode="json") for entry in entries],
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    digest = hashlib.sha256(serialized).hexdigest()
    return f"{VECTOR_INDEX_FINGERPRINT_ALGORITHM}:{digest}"


def _validate_provider(provider: EmbeddingProvider) -> None:
    _validate_selected_model_identity(
        model_id=provider.model_id,
        revision=provider.revision,
        dimension=provider.dimension,
        query_prefix=provider.query_prefix,
        document_prefix=provider.document_prefix,
    )


def _validate_selected_model_identity(
    *,
    model_id: str,
    revision: str,
    dimension: int,
    query_prefix: str,
    document_prefix: str,
) -> None:
    expected = (
        DEFAULT_EMBEDDING_MODEL_ID,
        DEFAULT_EMBEDDING_MODEL_REVISION,
        DEFAULT_EMBEDDING_DIMENSION,
        DEFAULT_QUERY_PREFIX,
        DEFAULT_DOCUMENT_PREFIX,
    )
    actual = (
        model_id,
        revision,
        dimension,
        query_prefix,
        document_prefix,
    )
    if actual != expected:
        raise ValueError("embedding model identity does not match vector_v1")


def _normalize_embedding_batch(
    embeddings: Sequence[Sequence[float]],
    *,
    expected_count: int,
    dimension: int,
    label: str,
) -> tuple[tuple[float, ...], ...]:
    try:
        concrete = list(embeddings)
    except TypeError as exc:
        raise ValueError(f"{label} must be a sequence") from exc
    if len(concrete) != expected_count:
        raise ValueError(
            f"{label} returned {len(concrete)} vectors; expected {expected_count}"
        )
    return tuple(
        _normalize_embedding(vector, dimension=dimension, label=label)
        for vector in concrete
    )


def _normalize_embedding(
    embedding: Sequence[float],
    *,
    dimension: int,
    label: str,
) -> tuple[float, ...]:
    try:
        raw_values = list(embedding)
    except TypeError as exc:
        raise ValueError(f"{label} vectors must be sequences") from exc
    if len(raw_values) != dimension:
        raise ValueError(
            f"{label} vectors must have dimension {dimension}; got {len(raw_values)}"
        )

    values: list[float] = []
    for component in raw_values:
        if isinstance(component, bool) or not isinstance(component, Real):
            raise ValueError(f"{label} components must be real numbers")
        numeric = float(component)
        if not isfinite(numeric):
            raise ValueError(f"{label} components must be finite")
        values.append(numeric)

    scale = max(abs(component) for component in values)
    if scale == 0.0:
        raise ValueError(f"{label} vectors must not be zero")
    scaled_values = [component / scale for component in values]
    norm = sqrt(
        sum(component * component for component in scaled_values)
    )
    return tuple(
        round(component / norm, VECTOR_COMPONENT_PRECISION)
        for component in scaled_values
    )
