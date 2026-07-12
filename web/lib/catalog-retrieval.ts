import type {
  CatalogRetrievalArtifact,
  CatalogRetrievalRecipe,
  CatalogRetrievalTool,
  TrustStatus,
} from "@/lib/types";

export const DEFAULT_TOP_TOOL_COUNT = 5;
export const DEFAULT_MATCHED_TERM_COUNT = 6;

const TRUST_STATUSES = new Set<TrustStatus>([
  "catalog-approved",
  "auto-validated",
  "experimental",
  "rejected",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isTrustStatus(value: unknown): value is TrustStatus {
  return typeof value === "string" && TRUST_STATUSES.has(value as TrustStatus);
}

function isCatalogRetrievalRecipe(value: unknown): value is CatalogRetrievalRecipe {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    Number.isFinite(value.score) &&
    isStringArray(value.matched_terms) &&
    isStringArray(value.matched_fields) &&
    typeof value.reason === "string"
  );
}

function isCatalogRetrievalTool(value: unknown): value is CatalogRetrievalTool {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.version === "string" &&
    Number.isFinite(value.score) &&
    isStringArray(value.matched_terms) &&
    isStringArray(value.matched_fields) &&
    isTrustStatus(value.trust_status) &&
    typeof value.reason === "string"
  );
}

function isCatalogRetrievalArtifact(value: unknown): value is CatalogRetrievalArtifact {
  return (
    isRecord(value) &&
    typeof value.query === "string" &&
    typeof value.strategy === "string" &&
    Array.isArray(value.recipes) &&
    value.recipes.every(isCatalogRetrievalRecipe) &&
    Array.isArray(value.tools) &&
    value.tools.every(isCatalogRetrievalTool) &&
    typeof value.fallback_used === "boolean" &&
    (value.fallback_reason === null || typeof value.fallback_reason === "string")
  );
}

export function hasCatalogRetrieval(
  retrieval: unknown,
): retrieval is CatalogRetrievalArtifact {
  if (!isCatalogRetrievalArtifact(retrieval)) {
    return false;
  }
  return Boolean(
    retrieval.query.trim() ||
      retrieval.recipes.length ||
      retrieval.tools.length ||
      retrieval.fallback_used,
  );
}

export function getTopCatalogRecipe(
  retrieval: CatalogRetrievalArtifact | null,
): CatalogRetrievalRecipe | null {
  return hasCatalogRetrieval(retrieval) ? retrieval.recipes[0] ?? null : null;
}

export function getTopCatalogTools(
  retrieval: CatalogRetrievalArtifact | null,
  limit = DEFAULT_TOP_TOOL_COUNT,
): CatalogRetrievalTool[] {
  if (!hasCatalogRetrieval(retrieval) || limit < 1) {
    return [];
  }
  return retrieval.tools.slice(0, limit);
}

export function summarizeMatchedTerms(
  terms: string[],
  limit = DEFAULT_MATCHED_TERM_COUNT,
): { visibleTerms: string[]; hiddenCount: number } {
  if (limit < 1) {
    return { visibleTerms: [], hiddenCount: terms.length };
  }
  return {
    visibleTerms: terms.slice(0, limit),
    hiddenCount: Math.max(terms.length - limit, 0),
  };
}

export function formatRetrievalScore(score: number): string {
  if (!Number.isFinite(score)) {
    return "0";
  }
  return Number.isInteger(score) ? String(score) : score.toFixed(1);
}
