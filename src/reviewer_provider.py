from __future__ import annotations

import json
import os
import re
from typing import Any, Protocol

from langchain_deepseek import ChatDeepSeek
from pydantic import SecretStr, ValidationError

from src.prompts import render_reviewer_repair_prompt
from src.reviewer_repair import ReviewerRepairRequest, ReviewerRepairResult


DEFAULT_REVIEWER_MODEL = "deepseek-v4-pro"
JSON_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


class ReviewerProviderError(ValueError):
    """Base error for the Reviewer provider boundary."""


class ReviewerProviderUnavailableError(ReviewerProviderError):
    """Raised when Reviewer repair was enabled without an available provider."""


class ReviewerProviderResponseError(ReviewerProviderError):
    """Raised when a provider response cannot be parsed into the result contract."""


class ReviewerLlm(Protocol):
    def invoke(self, input: Any, *args: Any, **kwargs: Any) -> Any:
        ...


class ReviewerRepairProvider(Protocol):
    def repair(self, request: ReviewerRepairRequest) -> ReviewerRepairResult:
        ...


class LlmReviewerRepairProvider:
    """Invoke an LLM and return only a parsed Reviewer repair result."""

    def __init__(self, llm: ReviewerLlm):
        self._llm = llm

    def repair(self, request: ReviewerRepairRequest) -> ReviewerRepairResult:
        prompt = render_reviewer_repair_prompt(request.model_dump(mode="json"))
        response = self._llm.invoke(prompt)
        raw_content = str(getattr(response, "content", response))
        return parse_reviewer_repair_response(raw_content)


def make_default_reviewer_provider(
    model: str = DEFAULT_REVIEWER_MODEL,
) -> ReviewerRepairProvider:
    """Create the default provider only when Reviewer repair is explicitly enabled."""
    api_key_raw = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key_raw:
        raise ReviewerProviderUnavailableError(
            "Reviewer repair is enabled but DEEPSEEK_API_KEY is not configured."
        )

    return LlmReviewerRepairProvider(
        ChatDeepSeek(
            model=model,
            api_key=SecretStr(api_key_raw),
            base_url="https://api.deepseek.com",
            temperature=0,
        )
    )


def parse_reviewer_repair_response(text: str) -> ReviewerRepairResult:
    """Parse a JSON-only provider response without retaining the raw text."""
    candidate = _extract_json_candidate(text)
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise ReviewerProviderResponseError("Reviewer response is not valid JSON.") from exc
    return coerce_reviewer_repair_result(payload)


def coerce_reviewer_repair_result(value: Any) -> ReviewerRepairResult:
    """Validate provider output while excluding raw values from error messages."""
    try:
        return ReviewerRepairResult.model_validate(value)
    except ValidationError as exc:
        details = "; ".join(
            f"{_format_location(error['loc'])}: {error['msg']}"
            for error in exc.errors(include_input=False, include_url=False)
        )
        raise ReviewerProviderResponseError(
            f"Reviewer response does not match the result schema: {details}"
        ) from exc


def _extract_json_candidate(text: str) -> str:
    stripped = text.strip()
    fenced = JSON_FENCE_PATTERN.search(stripped)
    if fenced:
        return fenced.group(1).strip()

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ReviewerProviderResponseError(
            "Reviewer response does not contain a JSON object."
        )
    return stripped[start : end + 1]


def _format_location(location: tuple[Any, ...]) -> str:
    if not location:
        return "result"
    return ".".join(str(part) for part in location)
