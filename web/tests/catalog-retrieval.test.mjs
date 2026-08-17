import assert from "node:assert/strict";
import test from "node:test";

import {
  formatRetrievalScore,
  getTopCatalogRecipe,
  getTopCatalogTools,
  hasCatalogRetrieval,
  summarizeMatchedTerms,
} from "../lib/catalog-retrieval.ts";

const retrieval = {
  query: "Run bulk RNA-seq differential expression.",
  strategy: "lexical_v1",
  recipes: [
    {
      id: "rnaseq_differential_expression",
      score: 22,
      matched_terms: ["rna", "seq", "differential", "expression"],
      matched_fields: ["id", "description", "steps.role"],
      reason: "Matched approved catalog recipe fields.",
    },
  ],
  tools: [
    {
      id: "deseq2",
      version: "1.42.1",
      score: 8.5,
      matched_terms: ["differential", "expression"],
      matched_fields: ["id", "description"],
      trust_status: "catalog-approved",
      execution_verification: {
        status: "e2e-validated",
        evidence: ["docs/test-cases.md"],
      },
      reason: "Matched approved catalog tool fields.",
    },
    {
      id: "salmon",
      version: "1.9.0",
      score: 5,
      matched_terms: ["quantification"],
      matched_fields: ["description"],
      trust_status: "catalog-approved",
      execution_verification: {
        status: "e2e-validated",
        evidence: ["docs/test-cases.md"],
      },
      reason: "Matched approved catalog tool fields.",
    },
  ],
  fallback_used: false,
  fallback_reason: null,
};

test("detects non-empty catalog retrieval artifacts", () => {
  assert.equal(hasCatalogRetrieval(undefined), false);
  assert.equal(hasCatalogRetrieval(null), false);
  assert.equal(hasCatalogRetrieval({}), false);
  assert.equal(
    hasCatalogRetrieval({
      query: "Run bulk RNA-seq differential expression.",
      recipes: [],
      tools: [],
    }),
    false,
  );
  assert.equal(
    hasCatalogRetrieval({
      ...retrieval,
      tools: [{ id: "deseq2" }],
    }),
    false,
  );
  assert.equal(
    hasCatalogRetrieval({
      ...retrieval,
      tools: [
        {
          ...retrieval.tools[0],
          execution_verification: { status: "e2e-validated", evidence: [] },
        },
      ],
    }),
    false,
  );
  assert.equal(
    hasCatalogRetrieval({
      query: "",
      strategy: "lexical_v1",
      recipes: [],
      tools: [],
      fallback_used: false,
      fallback_reason: null,
    }),
    false,
  );
  assert.equal(hasCatalogRetrieval(retrieval), true);
});

test("accepts legacy retrieval tools without execution verification", () => {
  const legacyRetrieval = {
    ...retrieval,
    tools: retrieval.tools.map(({ execution_verification: _verification, ...tool }) => tool),
  };

  assert.equal(hasCatalogRetrieval(legacyRetrieval), true);
});

test("selects top catalog recipe and limited tools", () => {
  assert.equal(getTopCatalogRecipe(retrieval)?.id, "rnaseq_differential_expression");
  assert.deepEqual(
    getTopCatalogTools(retrieval, 1).map((tool) => `${tool.id}:${tool.version}`),
    ["deseq2:1.42.1"],
  );
  assert.deepEqual(getTopCatalogTools(retrieval, 0), []);
});

test("summarizes matched terms with overflow count", () => {
  assert.deepEqual(summarizeMatchedTerms(["rna", "seq", "deg"], 2), {
    visibleTerms: ["rna", "seq"],
    hiddenCount: 1,
  });
  assert.deepEqual(summarizeMatchedTerms(["rna", "seq"], 4), {
    visibleTerms: ["rna", "seq"],
    hiddenCount: 0,
  });
});

test("formats retrieval scores compactly", () => {
  assert.equal(formatRetrievalScore(22), "22");
  assert.equal(formatRetrievalScore(8.53), "8.5");
  assert.equal(formatRetrievalScore(Number.NaN), "0");
});
