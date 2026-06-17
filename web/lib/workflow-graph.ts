import type { JsonObject, JsonValue } from "./types";

export type WorkflowGraphNodeKind =
  | "workflow-input"
  | "call"
  | "scatter"
  | "workflow-output";

export type WorkflowGraphEdgeKind = "input" | "dependency" | "output";

export type WorkflowGraphExpression = string | string[];

export type WorkflowGraphUnresolvedReason =
  | "unknown-call"
  | "unknown-output"
  | "unsupported-expression";

export type WorkflowGraphUnresolvedReference = {
  expression: string;
  ownerId: string;
  ownerKind: WorkflowGraphNodeKind;
  reason: WorkflowGraphUnresolvedReason;
  reference: string | null;
};

export type WorkflowGraphTaskOutput = {
  type: string | null;
  value: string | null;
};

export type WorkflowGraphNodeMetadata = {
  workflowInput?: {
    name: string;
    type: string;
  };
  call?: {
    id: string;
    task: string | null;
    inputs: Record<string, WorkflowGraphExpression>;
    outputs: Record<string, WorkflowGraphTaskOutput>;
    runtime: Record<string, JsonValue>;
    unresolvedReferences: WorkflowGraphUnresolvedReference[];
  };
  scatter?: {
    id: string;
    item: string | null;
    over: string | null;
    unresolvedReferences: WorkflowGraphUnresolvedReference[];
  };
  workflowOutput?: {
    name: string;
    expression: WorkflowGraphExpression;
    unresolvedReferences: WorkflowGraphUnresolvedReference[];
  };
};

export type WorkflowGraphNode = {
  id: string;
  kind: WorkflowGraphNodeKind;
  label: string;
  parentId: string | null;
  sourceStepId: string;
  metadata: WorkflowGraphNodeMetadata;
};

export type WorkflowGraphEdge = {
  id: string;
  source: string;
  target: string;
  kind: WorkflowGraphEdgeKind;
  label: string;
  expression: string;
  unresolved: false;
};

export type WorkflowGraph = {
  nodes: WorkflowGraphNode[];
  edges: WorkflowGraphEdge[];
  unresolvedReferences: WorkflowGraphUnresolvedReference[];
};

type WorkflowGraphCallInfo = {
  callId: string;
  nodeId: string;
  outputNames: Set<string> | null;
};

type PendingExpression = {
  ownerId: string;
  ownerKind: WorkflowGraphNodeKind;
  targetNodeId: string;
  label: string;
  value: unknown;
  callEdgeKind: WorkflowGraphEdgeKind;
  inputEdgeKind: WorkflowGraphEdgeKind;
};

type CallReference = {
  callId: string;
  outputName: string;
  text: string;
};

type InputReference = {
  inputName: string;
  text: string;
};

const CALL_REFERENCE_PATTERN =
  /\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b/g;
const IDENTIFIER_PATTERN = /\b[A-Za-z_][A-Za-z0-9_]*\b/g;
const RESERVED_IDENTIFIERS = new Set([
  "false",
  "flatten",
  "length",
  "null",
  "range",
  "read_json",
  "read_lines",
  "read_map",
  "read_string",
  "read_tsv",
  "select_all",
  "select_first",
  "true",
]);

export function buildWorkflowGraph(workflowIr: JsonObject): WorkflowGraph {
  const workflow = getRecord(workflowIr, "workflow");
  const tasks = getRecord(workflowIr, "tasks");

  const nodes: WorkflowGraphNode[] = [];
  const edges: WorkflowGraphEdge[] = [];
  const edgeKeys = new Set<string>();
  const unresolvedReferences: WorkflowGraphUnresolvedReference[] = [];
  const nodeById = new Map<string, WorkflowGraphNode>();
  const callInfoById = new Map<string, WorkflowGraphCallInfo>();
  const inputNames = new Set<string>();
  const pendingExpressions: PendingExpression[] = [];

  function addNode(node: WorkflowGraphNode): void {
    if (nodeById.has(node.id)) {
      return;
    }
    nodeById.set(node.id, node);
    nodes.push(node);
  }

  function addEdge(
    source: string,
    target: string,
    kind: WorkflowGraphEdgeKind,
    label: string,
    expression: string,
  ): void {
    const key = `${source}|${target}|${kind}|${label}|${expression}`;
    if (edgeKeys.has(key)) {
      return;
    }
    edgeKeys.add(key);
    edges.push({
      id: `edge:${edges.length + 1}`,
      source,
      target,
      kind,
      label,
      expression,
      unresolved: false,
    });
  }

  function addUnresolved(reference: WorkflowGraphUnresolvedReference): void {
    unresolvedReferences.push(reference);
    const node = nodeById.get(reference.ownerId);
    if (!node) {
      return;
    }

    const metadata = node.metadata;
    if (node.kind === "call" && metadata.call) {
      metadata.call.unresolvedReferences.push(reference);
    } else if (node.kind === "scatter" && metadata.scatter) {
      metadata.scatter.unresolvedReferences.push(reference);
    } else if (node.kind === "workflow-output" && metadata.workflowOutput) {
      metadata.workflowOutput.unresolvedReferences.push(reference);
    }
  }

  for (const [name, inputDefinition] of Object.entries(getRecord(workflow, "inputs"))) {
    inputNames.add(name);
    addNode({
      id: workflowInputNodeId(name),
      kind: "workflow-input",
      label: name,
      parentId: null,
      sourceStepId: name,
      metadata: {
        workflowInput: {
          name,
          type: normalizeInputType(inputDefinition),
        },
      },
    });
  }

  processSteps(normalizeWorkflowSteps(workflow), null);

  for (const [name, outputExpression] of Object.entries(getRecord(workflow, "outputs"))) {
    const nodeId = workflowOutputNodeId(name);
    addNode({
      id: nodeId,
      kind: "workflow-output",
      label: name,
      parentId: null,
      sourceStepId: name,
      metadata: {
        workflowOutput: {
          name,
          expression: normalizeExpression(outputExpression),
          unresolvedReferences: [],
        },
      },
    });
    pendingExpressions.push({
      ownerId: nodeId,
      ownerKind: "workflow-output",
      targetNodeId: nodeId,
      label: name,
      value: outputExpression,
      callEdgeKind: "output",
      inputEdgeKind: "output",
    });
  }

  for (const pendingExpression of pendingExpressions) {
    for (const expression of expressionTexts(pendingExpression.value)) {
      if (isUnsupportedExpression(expression)) {
        addUnresolved({
          expression,
          ownerId: pendingExpression.ownerId,
          ownerKind: pendingExpression.ownerKind,
          reason: "unsupported-expression",
          reference: null,
        });
        continue;
      }

      for (const callReference of findCallReferences(expression)) {
        const sourceCall = callInfoById.get(callReference.callId);
        if (!sourceCall) {
          addUnresolved({
            expression,
            ownerId: pendingExpression.ownerId,
            ownerKind: pendingExpression.ownerKind,
            reason: "unknown-call",
            reference: callReference.text,
          });
          continue;
        }

        if (
          sourceCall.outputNames !== null &&
          !sourceCall.outputNames.has(callReference.outputName)
        ) {
          addUnresolved({
            expression,
            ownerId: pendingExpression.ownerId,
            ownerKind: pendingExpression.ownerKind,
            reason: "unknown-output",
            reference: callReference.text,
          });
          continue;
        }

        addEdge(
          sourceCall.nodeId,
          pendingExpression.targetNodeId,
          pendingExpression.callEdgeKind,
          pendingExpression.label,
          expression,
        );
      }

      for (const inputReference of findInputReferences(expression, inputNames)) {
        addEdge(
          workflowInputNodeId(inputReference.inputName),
          pendingExpression.targetNodeId,
          pendingExpression.inputEdgeKind,
          pendingExpression.label,
          expression,
        );
      }
    }
  }

  return {
    nodes,
    edges,
    unresolvedReferences,
  };

  function processSteps(steps: Record<string, unknown>[], parentId: string | null): void {
    for (const step of steps) {
      const kind = typeof step.kind === "string" ? step.kind : step.task ? "call" : null;
      if (kind === "call") {
        processCallStep(step, parentId);
      } else if (kind === "scatter") {
        processScatterStep(step, parentId);
      }
    }
  }

  function processCallStep(step: Record<string, unknown>, parentId: string | null): void {
    const callId = getString(step.id);
    if (!callId) {
      return;
    }

    const nodeId = callNodeId(callId);
    const taskName = getString(step.task);
    const taskDefinition = taskName ? getRecord(tasks, taskName) : {};
    const outputs = normalizeTaskOutputs(getRecord(taskDefinition, "outputs"));
    const runtime = normalizeRuntime(getRecord(taskDefinition, "runtime"));
    const inputs = normalizeInputs(getRecord(step, "inputs"));

    addNode({
      id: nodeId,
      kind: "call",
      label: callId,
      parentId,
      sourceStepId: callId,
      metadata: {
        call: {
          id: callId,
          task: taskName,
          inputs,
          outputs,
          runtime,
          unresolvedReferences: [],
        },
      },
    });

    callInfoById.set(callId, {
      callId,
      nodeId,
      outputNames: Object.keys(outputs).length > 0 ? new Set(Object.keys(outputs)) : null,
    });

    for (const [inputName, inputExpression] of Object.entries(getRecord(step, "inputs"))) {
      pendingExpressions.push({
        ownerId: nodeId,
        ownerKind: "call",
        targetNodeId: nodeId,
        label: inputName,
        value: inputExpression,
        callEdgeKind: "dependency",
        inputEdgeKind: "input",
      });
    }
  }

  function processScatterStep(step: Record<string, unknown>, parentId: string | null): void {
    const scatterId = getString(step.id);
    if (!scatterId) {
      return;
    }

    const nodeId = scatterNodeId(scatterId);
    const overExpression = getString(step.over);
    addNode({
      id: nodeId,
      kind: "scatter",
      label: scatterId,
      parentId,
      sourceStepId: scatterId,
      metadata: {
        scatter: {
          id: scatterId,
          item: getString(step.item),
          over: overExpression,
          unresolvedReferences: [],
        },
      },
    });

    if (overExpression) {
      pendingExpressions.push({
        ownerId: nodeId,
        ownerKind: "scatter",
        targetNodeId: nodeId,
        label: "over",
        value: overExpression,
        callEdgeKind: "dependency",
        inputEdgeKind: "input",
      });
    }

    processSteps(normalizeStepArray(step.body), nodeId);
  }
}

function normalizeWorkflowSteps(workflow: Record<string, unknown>): Record<string, unknown>[] {
  const steps = normalizeStepArray(workflow.steps);
  if (steps.length > 0) {
    return steps;
  }

  return normalizeStepArray(workflow.calls).map((call) => ({
    ...call,
    kind: "call",
  }));
}

function normalizeStepArray(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) {
    return [];
  }

  return value.filter(isRecord);
}

function normalizeInputType(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (isRecord(value) && typeof value.type === "string") {
    return value.type;
  }
  return "unknown";
}

function normalizeInputs(value: Record<string, unknown>): Record<string, WorkflowGraphExpression> {
  return Object.fromEntries(
    Object.entries(value).map(([name, inputValue]) => [name, normalizeExpression(inputValue)]),
  );
}

function normalizeTaskOutputs(
  value: Record<string, unknown>,
): Record<string, WorkflowGraphTaskOutput> {
  return Object.fromEntries(
    Object.entries(value).map(([name, outputValue]) => {
      if (isRecord(outputValue)) {
        return [
          name,
          {
            type: getString(outputValue.type),
            value: expressionText(outputValue.value),
          },
        ];
      }

      return [
        name,
        {
          type: typeof outputValue === "string" ? outputValue : null,
          value: null,
        },
      ];
    }),
  );
}

function normalizeRuntime(value: Record<string, unknown>): Record<string, JsonValue> {
  return Object.fromEntries(
    Object.entries(value).filter((entry): entry is [string, JsonValue] => isJsonValue(entry[1])),
  );
}

function normalizeExpression(value: unknown): WorkflowGraphExpression {
  if (Array.isArray(value)) {
    return value.map((item) => expressionText(item) ?? stableJson(item));
  }

  return expressionText(value) ?? stableJson(value);
}

function expressionTexts(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.flatMap(expressionTexts);
  }

  const text = expressionText(value);
  return text ? [text] : [];
}

function expressionText(value: unknown): string | null {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (value === null || value === undefined) {
    return null;
  }
  if (isRecord(value) && "value" in value) {
    return expressionText(value.value);
  }
  return null;
}

function findCallReferences(expression: string): CallReference[] {
  return [...maskQuotedText(expression).matchAll(CALL_REFERENCE_PATTERN)].map((match) => ({
    callId: match[1],
    outputName: match[2],
    text: `${match[1]}.${match[2]}`,
  }));
}

function findInputReferences(
  expression: string,
  inputNames: Set<string>,
): InputReference[] {
  const maskedExpression = maskQuotedText(expression);
  const callReferenceSpans = [...maskedExpression.matchAll(CALL_REFERENCE_PATTERN)].map(
    (match) => ({
      start: match.index ?? 0,
      end: (match.index ?? 0) + match[0].length,
    }),
  );
  const references = new Map<string, InputReference>();

  for (const match of maskedExpression.matchAll(IDENTIFIER_PATTERN)) {
    const token = match[0];
    const start = match.index ?? 0;
    const end = start + token.length;

    if (
      RESERVED_IDENTIFIERS.has(token) ||
      !inputNames.has(token) ||
      callReferenceSpans.some((span) => start >= span.start && end <= span.end)
    ) {
      continue;
    }

    references.set(token, {
      inputName: token,
      text: token,
    });
  }

  return [...references.values()];
}

function isUnsupportedExpression(expression: string): boolean {
  const maskedExpression = maskQuotedText(expression);
  return /(?:\+|&&|\|\|)/.test(maskedExpression) || /\s(?:-|\*|\/)\s/.test(maskedExpression);
}

function workflowInputNodeId(name: string): string {
  return `input:${name}`;
}

function callNodeId(id: string): string {
  return `call:${id}`;
}

function scatterNodeId(id: string): string {
  return `scatter:${id}`;
}

function workflowOutputNodeId(name: string): string {
  return `output:${name}`;
}

function getRecord(source: Record<string, unknown>, key: string): Record<string, unknown> {
  const value = source[key];
  return isRecord(value) ? value : {};
}

function getString(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isJsonValue(value: unknown): value is JsonValue {
  if (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  ) {
    return true;
  }
  if (Array.isArray(value)) {
    return value.every(isJsonValue);
  }
  if (isRecord(value)) {
    return Object.values(value).every(isJsonValue);
  }
  return false;
}

function stableJson(value: unknown): string {
  if (value === undefined) {
    return "";
  }
  return JSON.stringify(value);
}

function maskQuotedText(value: string): string {
  return value.replace(/"([^"\\]|\\.)*"|'([^'\\]|\\.)*'/g, (match) => " ".repeat(match.length));
}
