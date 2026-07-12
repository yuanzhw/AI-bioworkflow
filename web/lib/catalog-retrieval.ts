import type {
  CatalogRetrievalArtifact,
  CatalogRetrievalRecipe,
  CatalogRetrievalTool,
} from "@/lib/types";

export const DEFAULT_TOP_TOOL_COUNT = 5;
export const DEFAULT_MATCHED_TERM_COUNT = 6;

export function hasCatalogRetrieval(
  retrieval: CatalogRetrievalArtifact | null,
): retrieval is CatalogRetrievalArtifact {
  if (retrieval === null) {
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
