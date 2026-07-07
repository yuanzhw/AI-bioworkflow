"use client";

import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { AlertCircle, Box, Database, FileOutput, GitBranch, Layers3 } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import type { WorkflowGraphNode, WorkflowGraphNodeKind } from "@/lib/workflow-graph";

export type WorkflowGraphNodeStatus =
  | "available"
  | "unresolved"
  | "unavailable";

export type WorkflowGraphNodeData = {
  graphNode: WorkflowGraphNode;
  status: WorkflowGraphNodeStatus;
  unresolvedCount: number;
};

export type WorkflowGraphReactNode = Node<WorkflowGraphNodeData, "workflowGraphNode">;

const kindLabels: Record<WorkflowGraphNodeKind, string> = {
  "workflow-input": "Input",
  call: "Call",
  scatter: "Scatter",
  "workflow-output": "Output",
};

const statusLabels: Record<WorkflowGraphNodeStatus, string> = {
  available: "结构可用",
  unresolved: "引用待审阅",
  unavailable: "DAG 不可用",
};

const kindIcons: Record<WorkflowGraphNodeKind, LucideIcon> = {
  "workflow-input": Database,
  call: Box,
  scatter: GitBranch,
  "workflow-output": FileOutput,
};

const statusClassNames: Record<WorkflowGraphNodeStatus, string> = {
  available: "border-primary/40 bg-secondary text-primary",
  unresolved: "border-destructive/40 bg-destructive text-destructive-foreground",
  unavailable: "border-muted-foreground/20 text-muted-foreground",
};

function formatUnresolvedCount(unresolvedCount: number): string {
  if (unresolvedCount === 0) {
    return "Workflow IR 节点";
  }
  if (unresolvedCount === 1) {
    return "1 条未解析引用";
  }
  return `${unresolvedCount} 条未解析引用`;
}

export function WorkflowNode({ data, selected }: NodeProps<WorkflowGraphReactNode>) {
  const { graphNode, status, unresolvedCount } = data;
  const Icon = kindIcons[graphNode.kind];
  const isScatter = graphNode.kind === "scatter";

  return (
    <div
      className={cn(
        "h-full rounded-md border bg-white p-3 shadow-sm transition-colors",
        selected ? "border-primary ring-2 ring-primary/20" : "border-border",
        isScatter && "bg-secondary/50",
      )}
    >
      {graphNode.kind !== "workflow-input" ? (
        <Handle
          type="target"
          position={Position.Left}
          className="!h-2.5 !w-2.5 !border-2 !border-white !bg-primary"
        />
      ) : null}

      <div className="flex min-w-0 items-start gap-2">
        <div className="rounded-md border bg-background p-1.5">
          <Icon className="h-4 w-4 text-primary" />
        </div>
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold">{graphNode.label}</div>
          <div className="mt-1 flex flex-wrap gap-1.5">
            <Badge variant="outline">{kindLabels[graphNode.kind]}</Badge>
            <Badge variant="outline" className={statusClassNames[status]}>
              {statusLabels[status]}
            </Badge>
          </div>
        </div>
      </div>

      {!isScatter ? (
        <div className="mt-3 flex items-center gap-1.5 text-xs text-muted-foreground">
          {unresolvedCount ? (
            <AlertCircle className="h-3.5 w-3.5 text-destructive" />
          ) : (
            <Layers3 className="h-3.5 w-3.5" />
          )}
          {formatUnresolvedCount(unresolvedCount)}
        </div>
      ) : (
        <div className="mt-3 flex items-center gap-1.5 text-xs leading-5 text-muted-foreground">
          {unresolvedCount ? (
            <AlertCircle className="h-3.5 w-3.5 text-destructive" />
          ) : (
            <Layers3 className="h-3.5 w-3.5" />
          )}
          {unresolvedCount ? formatUnresolvedCount(unresolvedCount) : "scatter group"}
        </div>
      )}

      {graphNode.kind !== "workflow-output" ? (
        <Handle
          type="source"
          position={Position.Right}
          className="!h-2.5 !w-2.5 !border-2 !border-white !bg-primary"
        />
      ) : null}
    </div>
  );
}
