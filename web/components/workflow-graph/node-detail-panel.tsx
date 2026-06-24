"use client";

import { Activity, AlertCircle, Box, FileOutput, GitBranch, Info } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { runEventLabels } from "@/lib/run-events";
import type { JsonValue, RunEvent } from "@/lib/types";
import type {
  WorkflowGraphExpression,
  WorkflowGraphNode,
  WorkflowGraphTaskOutput,
} from "@/lib/workflow-graph";
import type { WorkflowGraphNodeStatus } from "./workflow-node";

const statusLabels: Record<WorkflowGraphNodeStatus, string> = {
  pending: "Pending",
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  unavailable: "Unavailable",
};

function formatExpression(value: WorkflowGraphExpression): string {
  return Array.isArray(value) ? value.join("\n") : value;
}

function KeyValueList({ values }: { values: Record<string, string> }) {
  const entries = Object.entries(values);
  if (!entries.length) {
    return <div className="text-sm text-muted-foreground">暂无记录。</div>;
  }

  return (
    <div className="grid gap-2">
      {entries.map(([key, value]) => (
        <div key={key} className="grid gap-1 rounded-md border bg-background p-3">
          <div className="text-xs font-medium text-muted-foreground">{key}</div>
          <pre className="whitespace-pre-wrap break-words font-mono text-xs leading-5">{value}</pre>
        </div>
      ))}
    </div>
  );
}

function outputValues(outputs: Record<string, WorkflowGraphTaskOutput>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(outputs).map(([name, output]) => [
      name,
      [output.type, output.value].filter(Boolean).join(" = ") || "未记录",
    ]),
  );
}

function runtimeValues(runtime: Record<string, JsonValue>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(runtime).map(([key, value]) => [key, JSON.stringify(value)]),
  );
}

export function NodeDetailPanel({
  node,
  relatedEvents,
  status,
}: {
  node: WorkflowGraphNode | null;
  relatedEvents: RunEvent[];
  status: WorkflowGraphNodeStatus;
}) {
  if (!node) {
    return (
      <aside className="rounded-md border bg-white p-5">
        <div className="flex items-center gap-2 font-semibold">
          <Info className="h-5 w-5 text-primary" />
          节点详情
        </div>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">请选择图中的节点。</p>
      </aside>
    );
  }

  const metadata = node.metadata;
  const unresolvedReferences = [
    ...(metadata.call?.unresolvedReferences ?? []),
    ...(metadata.scatter?.unresolvedReferences ?? []),
    ...(metadata.workflowOutput?.unresolvedReferences ?? []),
  ];

  return (
    <aside className="rounded-md border bg-white p-5">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-semibold">{node.label}</h3>
        <Badge variant="outline">{node.kind}</Badge>
        <Badge variant="secondary">{statusLabels[status]}</Badge>
      </div>
      <p className="mt-2 break-all font-mono text-xs text-muted-foreground">{node.sourceStepId}</p>

      {metadata.workflowInput ? (
        <section className="mt-5">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
            <Info className="h-4 w-4 text-primary" />
            Workflow input
          </div>
          <KeyValueList values={{ type: metadata.workflowInput.type }} />
        </section>
      ) : null}

      {metadata.call ? (
        <>
          <section className="mt-5">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
              <Box className="h-4 w-4 text-primary" />
              Task
            </div>
            <KeyValueList values={{ task: metadata.call.task ?? "未记录" }} />
          </section>
          <section className="mt-5">
            <div className="mb-2 text-sm font-semibold">Inputs</div>
            <KeyValueList
              values={Object.fromEntries(
                Object.entries(metadata.call.inputs).map(([name, value]) => [
                  name,
                  formatExpression(value),
                ]),
              )}
            />
          </section>
          <section className="mt-5">
            <div className="mb-2 text-sm font-semibold">Outputs</div>
            <KeyValueList values={outputValues(metadata.call.outputs)} />
          </section>
          <section className="mt-5">
            <div className="mb-2 text-sm font-semibold">Runtime</div>
            <KeyValueList values={runtimeValues(metadata.call.runtime)} />
          </section>
        </>
      ) : null}

      {metadata.scatter ? (
        <section className="mt-5">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
            <GitBranch className="h-4 w-4 text-primary" />
            Scatter
          </div>
          <KeyValueList
            values={{
              item: metadata.scatter.item ?? "未记录",
              over: metadata.scatter.over ?? "未记录",
            }}
          />
        </section>
      ) : null}

      {metadata.workflowOutput ? (
        <section className="mt-5">
          <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
            <FileOutput className="h-4 w-4 text-primary" />
            Workflow output
          </div>
          <KeyValueList
            values={{
              expression: formatExpression(metadata.workflowOutput.expression),
            }}
          />
        </section>
      ) : null}

      {unresolvedReferences.length ? (
        <section className="mt-5 rounded-md border border-destructive/40 bg-background p-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-destructive">
            <AlertCircle className="h-4 w-4" />
            Unresolved references
          </div>
          <ul className="mt-3 grid gap-2 text-xs leading-5 text-muted-foreground">
            {unresolvedReferences.map((reference, index) => (
              <li
                key={[
                  reference.ownerId,
                  reference.reference ?? "expression",
                  reference.expression,
                  reference.reason,
                  index,
                ].join(":")}
                className="break-words"
              >
                {reference.reason}: {reference.expression}
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section className="mt-5">
        <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
          <Activity className="h-4 w-4 text-primary" />
          Related events
        </div>
        {relatedEvents.length ? (
          <div className="grid gap-2">
            {relatedEvents.slice(-4).map((event) => (
              <div key={event.event_id} className="rounded-md border bg-background p-3">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <Badge variant="outline">#{event.sequence}</Badge>
                  <span className="font-medium">{runEventLabels[event.type]}</span>
                </div>
                <p className="mt-2 break-words text-xs leading-5 text-muted-foreground">
                  {event.summary}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <div className="rounded-md border bg-background p-3 text-sm text-muted-foreground">
            暂无关联事件。
          </div>
        )}
      </section>
    </aside>
  );
}
