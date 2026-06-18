import assert from "node:assert/strict";
import test from "node:test";

import { buildWorkflowGraph } from "../lib/workflow-graph.ts";

function nodeById(graph, id) {
  const node = graph.nodes.find((candidate) => candidate.id === id);
  assert.ok(node, `missing node ${id}`);
  return node;
}

function findEdge(graph, expected) {
  return graph.edges.find((edge) =>
    Object.entries(expected).every(([key, value]) => edge[key] === value),
  );
}

test("builds call dependency and workflow output graph from legacy calls", () => {
  const graph = buildWorkflowGraph({
    workflow: {
      name: "RNASeqPipeline",
      inputs: {
        raw_r1: "File",
        raw_r2: "File",
        reference: "File",
      },
      calls: [
        {
          id: "qc",
          task: "fastp",
          inputs: {
            r1: "raw_r1",
            r2: "raw_r2",
          },
        },
        {
          id: "align",
          task: "bwa_mem",
          inputs: {
            r1: "qc.clean_r1",
            r2: "qc.clean_r2",
            ref: "reference",
          },
        },
      ],
      outputs: {
        bam: "align.bam",
      },
    },
    tasks: {
      fastp: {
        outputs: {
          clean_r1: {
            type: "File",
            value: '"clean_R1.fq.gz"',
          },
          clean_r2: {
            type: "File",
            value: '"clean_R2.fq.gz"',
          },
        },
        runtime: {
          docker: "quay.io/biocontainers/fastp:1.3.3--h43da1c4_0",
        },
      },
      bwa_mem: {
        outputs: {
          bam: {
            type: "File",
            value: '"aligned.sam"',
          },
        },
        runtime: {
          docker: "quay.io/biocontainers/bwa:0.7.17--hed695b0_7",
          cpu: 8,
        },
      },
    },
  });

  assert.equal(nodeById(graph, "input:raw_r1").metadata.workflowInput.type, "File");
  assert.equal(nodeById(graph, "call:qc").metadata.call.task, "fastp");

  const alignNode = nodeById(graph, "call:align");
  assert.equal(alignNode.metadata.call.task, "bwa_mem");
  assert.equal(alignNode.metadata.call.outputs.bam.type, "File");
  assert.equal(
    alignNode.metadata.call.runtime.docker,
    "quay.io/biocontainers/bwa:0.7.17--hed695b0_7",
  );

  assert.ok(
    findEdge(graph, {
      source: "call:qc",
      target: "call:align",
      kind: "dependency",
      label: "r1",
      expression: "qc.clean_r1",
    }),
  );
  assert.ok(
    findEdge(graph, {
      source: "call:qc",
      target: "call:align",
      kind: "dependency",
      label: "r2",
      expression: "qc.clean_r2",
    }),
  );
  assert.ok(
    findEdge(graph, {
      source: "call:align",
      target: "output:bam",
      kind: "output",
      label: "bam",
      expression: "align.bam",
    }),
  );
  assert.deepEqual(graph.unresolvedReferences, []);
});

test("builds scatter group and nested call dependencies from workflow steps", () => {
  const graph = buildWorkflowGraph({
    workflow: {
      name: "RNASeqDEG",
      inputs: {
        sample_ids: "Array[String]",
        raw_r1s: "Array[File]",
        raw_r2s: "Array[File]",
        transcriptome_index: "File",
      },
      steps: [
        {
          id: "per_sample",
          kind: "scatter",
          item: "i",
          over: "range(length(sample_ids))",
          body: [
            {
              id: "qc",
              kind: "call",
              task: "fastp",
              inputs: {
                r1: "raw_r1s[i]",
                r2: "raw_r2s[i]",
              },
            },
            {
              id: "quantify",
              kind: "call",
              task: "salmon",
              inputs: {
                r1: "qc.clean_r1",
                r2: "qc.clean_r2",
                index: "transcriptome_index",
              },
            },
          ],
        },
        {
          id: "summarize",
          kind: "call",
          task: "tximport",
          inputs: {
            quant_files: "quantify.quant_file",
          },
        },
      ],
      outputs: {
        counts: "summarize.gene_counts",
      },
    },
    tasks: {
      fastp: {
        outputs: {
          clean_r1: {
            type: "File",
            value: '"clean_R1.fq.gz"',
          },
          clean_r2: {
            type: "File",
            value: '"clean_R2.fq.gz"',
          },
        },
      },
      salmon: {
        outputs: {
          quant_file: {
            type: "File",
            value: '"quant.sf"',
          },
        },
        runtime: {
          docker: "quay.io/biocontainers/salmon:1.9.0--h7e5ed60_0",
        },
      },
      tximport: {
        outputs: {
          gene_counts: {
            type: "File",
            value: '"gene_counts.tsv"',
          },
        },
      },
    },
  });

  const scatterNode = nodeById(graph, "scatter:per_sample");
  assert.equal(scatterNode.metadata.scatter.item, "i");
  assert.equal(scatterNode.metadata.scatter.over, "range(length(sample_ids))");
  assert.equal(nodeById(graph, "call:qc").parentId, "scatter:per_sample");
  assert.equal(nodeById(graph, "call:quantify").parentId, "scatter:per_sample");

  assert.ok(
    findEdge(graph, {
      source: "input:sample_ids",
      target: "scatter:per_sample",
      kind: "input",
      label: "over",
      expression: "range(length(sample_ids))",
    }),
  );
  assert.ok(
    findEdge(graph, {
      source: "call:qc",
      target: "call:quantify",
      kind: "dependency",
      label: "r1",
      expression: "qc.clean_r1",
    }),
  );
  assert.ok(
    findEdge(graph, {
      source: "call:quantify",
      target: "call:summarize",
      kind: "dependency",
      label: "quant_files",
      expression: "quantify.quant_file",
    }),
  );
  assert.ok(
    findEdge(graph, {
      source: "call:summarize",
      target: "output:counts",
      kind: "output",
      label: "counts",
      expression: "summarize.gene_counts",
    }),
  );
  assert.deepEqual(graph.unresolvedReferences, []);
});

test("records unresolved references without guessing unsupported expressions", () => {
  const graph = buildWorkflowGraph({
    workflow: {
      name: "UnresolvedDemo",
      inputs: {
        raw_r1: "File",
      },
      steps: [
        {
          id: "qc",
          kind: "call",
          task: "fastp",
          inputs: {
            r1: "raw_r1",
          },
        },
        {
          id: "report",
          kind: "call",
          task: "multiqc",
          inputs: {
            missing_call: "missing.result",
            missing_output: "qc.missing_report",
            unsupported: "qc.html_report + qc.json_report",
            unsupported_minus: "qc.html_report-qc.json_report",
            unsupported_multiply: "qc.html_report*qc.json_report",
          },
        },
      ],
      outputs: {
        report: "report.multiqc_report",
      },
    },
    tasks: {
      fastp: {
        outputs: {
          html_report: {
            type: "File",
            value: '"fastp.html"',
          },
          json_report: {
            type: "File",
            value: '"fastp.json"',
          },
        },
      },
      multiqc: {
        outputs: {
          multiqc_report: {
            type: "File",
            value: '"multiqc.html"',
          },
        },
      },
    },
  });

  assert.deepEqual(
    graph.unresolvedReferences.map((reference) => ({
      reason: reference.reason,
      reference: reference.reference,
      expression: reference.expression,
    })),
    [
      {
        reason: "unknown-call",
        reference: "missing.result",
        expression: "missing.result",
      },
      {
        reason: "unknown-output",
        reference: "qc.missing_report",
        expression: "qc.missing_report",
      },
      {
        reason: "unsupported-expression",
        reference: null,
        expression: "qc.html_report + qc.json_report",
      },
      {
        reason: "unsupported-expression",
        reference: null,
        expression: "qc.html_report-qc.json_report",
      },
      {
        reason: "unsupported-expression",
        reference: null,
        expression: "qc.html_report*qc.json_report",
      },
    ],
  );

  const reportNode = nodeById(graph, "call:report");
  assert.equal(reportNode.metadata.call.unresolvedReferences.length, 5);
  assert.equal(
    findEdge(graph, {
      source: "call:qc",
      target: "call:report",
      expression: "qc.html_report + qc.json_report",
    }),
    undefined,
  );
  assert.equal(
    findEdge(graph, {
      source: "call:qc",
      target: "call:report",
      expression: "qc.html_report-qc.json_report",
    }),
    undefined,
  );
  assert.equal(
    findEdge(graph, {
      source: "call:qc",
      target: "call:report",
      expression: "qc.html_report*qc.json_report",
    }),
    undefined,
  );
  assert.ok(
    findEdge(graph, {
      source: "call:report",
      target: "output:report",
      kind: "output",
      label: "report",
      expression: "report.multiqc_report",
    }),
  );
});
