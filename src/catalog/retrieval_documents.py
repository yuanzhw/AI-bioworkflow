"""Deterministic, versioned documents for approved Catalog retrieval."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.catalog.loader import ToolCatalog
from src.catalog.retriever import CATALOG_APPROVED_TRUST_STATUS
from src.catalog.schema import (
    ExecutionVerificationStatus,
    ToolParamSpec,
    ToolSpec,
    validate_identifier,
)
from src.recipes.loader import RecipeCatalog
from src.recipes.schema import RecipeSpec, RecipeStepSpec


CATALOG_RETRIEVAL_DOCUMENT_SCHEMA_VERSION = "1.0"
CATALOG_RETRIEVAL_CORPUS_SCHEMA_VERSION = "1.0"
CATALOG_RETRIEVAL_FINGERPRINT_ALGORITHM = "sha256"

CatalogRetrievalDocumentKind = Literal["recipe", "tool"]


class CatalogRetrievalDocumentSection(BaseModel):
    """A named, ordered source section rendered into embedding text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    values: tuple[str, ...]

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        normalized = value.strip()
        validate_identifier(normalized, "retrieval document section name")
        return normalized

    @field_validator("values")
    @classmethod
    def validate_values(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for item in value:
            text = item.strip()
            if not text:
                raise ValueError("retrieval document section values must not be empty")
            if text in normalized:
                raise ValueError("retrieval document section values must be unique")
            normalized.append(text)
        if not normalized:
            raise ValueError("retrieval document sections must contain at least one value")
        return tuple(normalized)


class CatalogRetrievalDocument(BaseModel):
    """A model-neutral recipe or tool document from the approved Catalog."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = CATALOG_RETRIEVAL_DOCUMENT_SCHEMA_VERSION
    document_id: str
    kind: CatalogRetrievalDocumentKind
    catalog_id: str
    catalog_version: str | None = None
    title: str
    sections: tuple[CatalogRetrievalDocumentSection, ...]
    text: str
    trust_status: Literal["catalog-approved"] | None = None
    execution_verification_status: ExecutionVerificationStatus | None = None
    execution_verification_evidence: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("catalog_id")
    @classmethod
    def validate_catalog_id(cls, value: str) -> str:
        validate_identifier(value, "retrieval document catalog id")
        return value

    @field_validator("catalog_version")
    @classmethod
    def validate_catalog_version(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("retrieval document catalog version must not be empty")
        return normalized

    @field_validator("title", "text")
    @classmethod
    def validate_non_empty_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("retrieval document title and text must not be empty")
        return normalized

    @field_validator("execution_verification_evidence")
    @classmethod
    def validate_verification_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for item in value:
            evidence = item.strip()
            if not evidence:
                raise ValueError("retrieval document verification evidence must not be empty")
            if evidence in normalized:
                raise ValueError("retrieval document verification evidence must be unique")
            normalized.append(evidence)
        return tuple(normalized)

    @model_validator(mode="after")
    def validate_identity_and_text(self):
        section_names = [section.name for section in self.sections]
        if not section_names:
            raise ValueError("retrieval documents must contain at least one section")
        if len(section_names) != len(set(section_names)):
            raise ValueError("retrieval document section names must be unique")

        expected_text = render_catalog_retrieval_document_text(self.sections)
        if self.text != expected_text:
            raise ValueError("retrieval document text must match its ordered sections")

        if self.kind == "recipe":
            expected_id = f"recipe:{self.catalog_id}"
            if self.catalog_version is not None:
                raise ValueError("recipe retrieval documents must not define catalog_version")
            if self.trust_status is not None:
                raise ValueError("recipe retrieval documents must not define trust_status")
            if self.execution_verification_status is not None:
                raise ValueError(
                    "recipe retrieval documents must not define execution verification"
                )
            if self.execution_verification_evidence:
                raise ValueError(
                    "recipe retrieval documents must not define verification evidence"
                )
        else:
            if self.catalog_version is None:
                raise ValueError("tool retrieval documents must define catalog_version")
            expected_id = f"tool:{self.catalog_id}@{self.catalog_version}"
            if self.trust_status != CATALOG_APPROVED_TRUST_STATUS:
                raise ValueError(
                    "tool retrieval documents must preserve catalog-approved trust status"
                )
            if self.execution_verification_status is None:
                raise ValueError(
                    "tool retrieval documents must define execution verification status"
                )
            if (
                self.execution_verification_status == "unverified"
                and self.execution_verification_evidence
            ):
                raise ValueError("unverified tool documents must not define evidence")
            if (
                self.execution_verification_status != "unverified"
                and not self.execution_verification_evidence
            ):
                raise ValueError(
                    "verified tool documents must define execution verification evidence"
                )

        if self.document_id != expected_id:
            raise ValueError(
                f"retrieval document id must be '{expected_id}' for this Catalog identity"
            )
        return self


class CatalogRetrievalCorpus(BaseModel):
    """Canonical approved Catalog documents and their content fingerprint."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = CATALOG_RETRIEVAL_CORPUS_SCHEMA_VERSION
    document_schema_version: Literal["1.0"] = CATALOG_RETRIEVAL_DOCUMENT_SCHEMA_VERSION
    fingerprint_algorithm: Literal["sha256"] = CATALOG_RETRIEVAL_FINGERPRINT_ALGORITHM
    fingerprint: str
    documents: tuple[CatalogRetrievalDocument, ...]

    @model_validator(mode="after")
    def validate_documents_and_fingerprint(self):
        document_ids = [document.document_id for document in self.documents]
        if not document_ids:
            raise ValueError("retrieval corpus must contain at least one document")
        if len(document_ids) != len(set(document_ids)):
            raise ValueError("retrieval corpus document ids must be unique")
        if document_ids != sorted(document_ids):
            raise ValueError("retrieval corpus documents must be sorted by document_id")

        expected_fingerprint = fingerprint_catalog_retrieval_documents(self.documents)
        if self.fingerprint != expected_fingerprint:
            raise ValueError(
                "retrieval corpus fingerprint must match its canonical documents"
            )
        return self


def build_catalog_retrieval_corpus(
    tool_catalog: ToolCatalog,
    recipe_catalog: RecipeCatalog,
) -> CatalogRetrievalCorpus:
    """Build the canonical retrieval corpus from approved local Catalog objects."""
    documents = tuple(
        sorted(
            (
                *(
                    _recipe_document(recipe, tool_catalog)
                    for recipe in recipe_catalog.all()
                ),
                *(_tool_document(tool) for tool in tool_catalog.all()),
            ),
            key=lambda document: document.document_id,
        )
    )
    return CatalogRetrievalCorpus(
        fingerprint=fingerprint_catalog_retrieval_documents(documents),
        documents=documents,
    )


def fingerprint_catalog_retrieval_documents(
    documents: Sequence[CatalogRetrievalDocument],
) -> str:
    """Return a stable fingerprint for canonical document content."""
    canonical_documents = sorted(documents, key=lambda document: document.document_id)
    payload = {
        "schema_version": CATALOG_RETRIEVAL_CORPUS_SCHEMA_VERSION,
        "document_schema_version": CATALOG_RETRIEVAL_DOCUMENT_SCHEMA_VERSION,
        "documents": [
            document.model_dump(mode="json") for document in canonical_documents
        ],
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{CATALOG_RETRIEVAL_FINGERPRINT_ALGORITHM}:{hashlib.sha256(serialized).hexdigest()}"


def render_catalog_retrieval_document_text(
    sections: Sequence[CatalogRetrievalDocumentSection],
) -> str:
    """Render ordered source sections into stable model input text."""
    return "\n".join(
        f"{section.name}: {' | '.join(section.values)}" for section in sections
    )


def _recipe_document(
    recipe: RecipeSpec,
    tool_catalog: ToolCatalog,
) -> CatalogRetrievalDocument:
    for step in recipe.steps:
        for tool_id in step.allowed_tools:
            if not tool_catalog.has_tool_id(tool_id):
                raise ValueError(
                    f"recipe '{recipe.id}' retrieval document references unknown approved "
                    f"tool '{tool_id}'"
                )

    sections = _sections(
        ("recipe_id", (recipe.id,)),
        ("name", (recipe.name,)),
        ("aliases", _sorted_text(recipe.aliases)),
        ("description", (recipe.description,)),
        (
            "required_inputs",
            (
                _named_type_description(name, spec.type, spec.description)
                for name, spec in sorted(recipe.required_inputs.items())
            ),
        ),
        ("steps", (_recipe_step_text(step) for step in recipe.steps)),
    )
    return CatalogRetrievalDocument(
        document_id=f"recipe:{recipe.id}",
        kind="recipe",
        catalog_id=recipe.id,
        title=recipe.name,
        sections=sections,
        text=render_catalog_retrieval_document_text(sections),
    )


def _tool_document(tool: ToolSpec) -> CatalogRetrievalDocument:
    sections = _sections(
        ("tool_id", (tool.id,)),
        ("version", (tool.version,)),
        ("aliases", _sorted_text(tool.aliases)),
        ("description", (tool.description,)),
        (
            "inputs",
            (
                _named_type_description(
                    name,
                    spec.type,
                    spec.description,
                    required=spec.required,
                )
                for name, spec in sorted(tool.inputs.items())
            ),
        ),
        (
            "parameters",
            (
                _tool_parameter_text(name, spec)
                for name, spec in sorted(tool.params.items())
            ),
        ),
        (
            "outputs",
            (
                _tool_output_text(
                    name,
                    spec.type,
                    spec.description,
                    spec.tags,
                )
                for name, spec in sorted(tool.outputs.items())
            ),
        ),
    )
    verification = tool.execution_verification
    return CatalogRetrievalDocument(
        document_id=f"tool:{tool.id}@{tool.version}",
        kind="tool",
        catalog_id=tool.id,
        catalog_version=tool.version,
        title=tool.id,
        sections=sections,
        text=render_catalog_retrieval_document_text(sections),
        trust_status=CATALOG_APPROVED_TRUST_STATUS,
        execution_verification_status=verification.status,
        execution_verification_evidence=tuple(verification.evidence),
    )


def _sections(
    *items: tuple[str, Iterable[str]],
) -> tuple[CatalogRetrievalDocumentSection, ...]:
    sections: list[CatalogRetrievalDocumentSection] = []
    for name, raw_values in items:
        values = tuple(value.strip() for value in raw_values if value.strip())
        if values:
            sections.append(CatalogRetrievalDocumentSection(name=name, values=values))
    return tuple(sections)


def _sorted_text(values: Iterable[str]) -> tuple[str, ...]:
    normalized = {value.strip() for value in values if value.strip()}
    return tuple(sorted(normalized, key=lambda value: (value.casefold(), value)))


def _named_type_description(
    name: str,
    value_type: str,
    description: str | None,
    *,
    required: bool | None = None,
) -> str:
    parts = [name, f"type={value_type}"]
    if required is not None:
        parts.append(f"required={str(required).lower()}")
    if description and description.strip():
        parts.append(description.strip())
    return "; ".join(parts)


def _recipe_step_text(step: RecipeStepSpec) -> str:
    parts = [
        step.id,
        f"role={step.role}",
        f"optional={str(step.optional).lower()}",
        f"allowed_tools={','.join(sorted(step.allowed_tools))}",
    ]
    if step.scatter is not None:
        parts.append(f"scatter={step.scatter.id}")
    return "; ".join(parts)


def _tool_parameter_text(name: str, spec: ToolParamSpec) -> str:
    parts = [
        name,
        f"type={spec.type}",
        f"required={str(spec.required).lower()}",
    ]
    if spec.default is not None:
        parts.append(
            "default="
            + json.dumps(
                spec.default,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    if spec.min is not None:
        parts.append(f"min={spec.min}")
    if spec.max is not None:
        parts.append(f"max={spec.max}")
    if spec.choices is not None:
        parts.append(
            "choices="
            + json.dumps(
                spec.choices,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        )
    if spec.description and spec.description.strip():
        parts.append(spec.description.strip())
    return "; ".join(parts)


def _tool_output_text(
    name: str,
    value_type: str,
    description: str | None,
    tags: Iterable[str],
) -> str:
    parts = [name, f"type={value_type}"]
    normalized_tags = _sorted_text(tags)
    if normalized_tags:
        parts.append(f"tags={','.join(normalized_tags)}")
    if description and description.strip():
        parts.append(description.strip())
    return "; ".join(parts)
