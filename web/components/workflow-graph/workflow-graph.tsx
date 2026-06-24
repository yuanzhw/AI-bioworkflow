"use client";

import {
  Background,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  type Edge,
  type NodeMouseHandler,
} from "@xyflow/react";
import { GitBranch, Loader2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { buildRunEventsUrl } from "@/lib/api";
import {
  isTerminalRunStatus,
  mergeRunEvent,
  parseRunEventMessage,
  readPayloadString,
  runEventTypes,
} from "@/lib/run-events";
import type { JsonObject, RunEvent, RunStatus } from "@/lib/types";
import {
  buildWorkflowGraph,
  type WorkflowGraph,
  type WorkflowGraphEdge,
  type WorkflowGraphNode,
} from "@/lib/workflow-graph";
import { cn } from "@/lib/utils";
import { GraphEmptyState } from "./graph-empty-state";
import { NodeDetailPanel } from "./node-detail-panel";
import {
  WorkflowNode,
  type WorkflowGraphNodeStatus,
  type WorkflowGraphReactNode,
} from "./workflow-node";

const nodeTypes = {
  workflowGraphNode: WorkflowNode,
};

const streamLabels: Record<WorkflowGraphStreamState, string> = {
  disabled: "无事件流",
  connecting: "连接中",
  connected: "读取事件",
  closed: "事件结束",
  error: "事件流中断",
};

const TOP_LEVEL_NODE_HEIGHT = 106;
const TOP_LEVEL_NODE_WIDTH = 252;
const SCATTER_HEADER_HEIGHT = 104;
const SCATTER_NODE_WIDTH = 336;
const CHILD_NODE_GAP = 18;
const CHILD_NODE_HEIGHT = 78;
const CHILD_NODE_WIDTH = 232;
const CHILD_NODE_X = 52;
const CHILD_NODE_Y = 94;
const COLUMN_GAP = 380;
const ROW_GAP = 32;

type WorkflowGraphStreamState = "disabled" | "connecting" | "connected" | "closed" | "error";

type PositionedNode = WorkflowGraphReactNode & {
  parentId?: string;
  extent?: "parent";
};

type NodeLayout = {
  height: number;
  width: number;
  x: number;
  y: number;
};

type GraphNodeView = {
  node: WorkflowGraphNode;
  relatedEvents: RunEvent[];
  status: WorkflowGraphNodeStatus;
};

export function WorkflowGraphPanel({
  eventsUrl,
  status,
  workflowIr,
}: {
  eventsUrl: string | null;
  status: RunStatus;
  workflowIr: JsonObject;
}) {
  const graph = useMemo(() => buildWorkflowGraph(workflowIr), [workflowIr]);
  const { events, streamState } = useWorkflowGraphEvents(eventsUrl, status);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);

  const graphNodesById = useMemo(
    () => new Map(graph.nodes.map((node) => [node.id, node])),
    [graph.nodes],
  );
  const nodeViews = useMemo(() => buildNodeViews(graph, events, status), [events, graph, status]);
  const { edges, nodes } = useMemo(
    () => toReactFlowElements(graph, nodeViews, selectedNodeId),
    [graph, nodeViews, selectedNodeId],
  );

  useEffect(() => {
    if (!graph.nodes.length) {
      setSelectedNodeId(null);
      return;
    }

    setSelectedNodeId((currentNodeId) => {
      if (currentNodeId && graphNodesById.has(currentNodeId)) {
        return currentNodeId;
      }
      return graph.nodes.find((node) => node.kind === "call")?.id ?? graph.nodes[0].id;
    });
  }, [graph.nodes, graphNodesById]);

  const selectedNode = selectedNodeId ? graphNodesById.get(selectedNodeId) ?? null : null;
  const selectedView = selectedNodeId ? nodeViews.get(selectedNodeId) : null;
  const handleNodeClick: NodeMouseHandler = (_, node) => {
    setSelectedNodeId(node.id);
  };

  return (
    <section className="mt-6 rounded-md border bg-white p-5">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <GitBranch className="h-5 w-5 text-primary" />
            <h2 className="font-semibold">Workflow DAG</h2>
            <Badge variant="outline">{graph.nodes.length} nodes</Badge>
            <Badge variant="outline">{graph.edges.length} edges</Badge>
          </div>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            基于 Workflow IR 的 inputs、steps、scatter 和 outputs 构建依赖图。
          </p>
        </div>
        <Badge
          variant={streamState === "connected" ? "secondary" : "outline"}
          className="gap-1.5"
        >
          {streamState === "connected" || streamState === "connecting" ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
          ) : null}
          {streamLabels[streamState]}
        </Badge>
      </div>

      {graph.nodes.length ? (
        <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="h-[38rem] overflow-hidden rounded-md border bg-background xl:h-[42rem]">
            <ReactFlowProvider>
              <ReactFlow
                fitView
                fitViewOptions={{ padding: 0.18 }}
                maxZoom={1.4}
                minZoom={0.35}
                nodeTypes={nodeTypes}
                nodes={nodes}
                edges={edges}
                nodesConnectable={false}
                nodesDraggable={false}
                onNodeClick={handleNodeClick}
                panOnScroll
                selectionOnDrag
              >
                <Background gap={18} size={1} />
                <MiniMap
                  pannable
                  zoomable
                  nodeColor={(node) => getMiniMapColor(node as WorkflowGraphReactNode)}
                  nodeStrokeWidth={3}
                />
                <Controls showInteractive={false} />
              </ReactFlow>
            </ReactFlowProvider>
          </div>
          <NodeDetailPanel
            node={selectedNode}
            relatedEvents={selectedView?.relatedEvents ?? []}
            status={selectedView?.status ?? "unavailable"}
          />
        </div>
      ) : (
        <GraphEmptyState />
      )}
    </section>
  );
}

function useWorkflowGraphEvents(
  eventsUrl: string | null,
  status: RunStatus,
): { events: RunEvent[]; streamState: WorkflowGraphStreamState } {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [streamState, setStreamState] = useState<WorkflowGraphStreamState>(
    eventsUrl ? "connecting" : "disabled",
  );

  useEffect(() => {
    if (!eventsUrl) {
      setStreamState("disabled");
      return undefined;
    }

    let isClosed = false;
    const eventSource = new EventSource(buildRunEventsUrl(eventsUrl));
    setStreamState("connecting");

    eventSource.onopen = () => {
      if (!isClosed) {
        setStreamState("connected");
      }
    };

    eventSource.onerror = () => {
      if (!isClosed) {
        setStreamState(isTerminalRunStatus(status) ? "closed" : "error");
      }
      if (isTerminalRunStatus(status)) {
        eventSource.close();
      }
    };

    const handlers = runEventTypes.map((eventType) => {
      const handler = (message: MessageEvent<string>) => {
        const parsed = parseRunEventMessage(message);
        if (!parsed) {
          return;
        }

        setEvents((currentEvents) => mergeRunEvent(currentEvents, parsed));
        if (parsed.type === "run.completed") {
          setStreamState("closed");
          eventSource.close();
        }
      };
      eventSource.addEventListener(eventType, handler);
      return { eventType, handler };
    });

    return () => {
      isClosed = true;
      handlers.forEach(({ eventType, handler }) => {
        eventSource.removeEventListener(eventType, handler);
      });
      eventSource.close();
    };
  }, [eventsUrl, status]);

  return { events, streamState };
}

function buildNodeViews(
  graph: WorkflowGraph,
  events: RunEvent[],
  runStatus: RunStatus,
): Map<string, GraphNodeView> {
  return new Map(
    graph.nodes.map((node) => {
      const relatedEvents = events.filter((event) => eventBelongsToNode(event, node));
      return [
        node.id,
        {
          node,
          relatedEvents,
          status: getNodeStatus(relatedEvents, runStatus),
        },
      ];
    }),
  );
}

function toReactFlowElements(
  graph: WorkflowGraph,
  nodeViews: Map<string, GraphNodeView>,
  selectedNodeId: string | null,
): { edges: Edge[]; nodes: WorkflowGraphReactNode[] } {
  const layouts = calculateNodeLayouts(graph);
  const nodes = graph.nodes.map((graphNode): PositionedNode => {
    const layout = layouts.get(graphNode.id) ?? {
      height: TOP_LEVEL_NODE_HEIGHT,
      width: TOP_LEVEL_NODE_WIDTH,
      x: 0,
      y: 0,
    };
    const nodeView = nodeViews.get(graphNode.id);

    return {
      id: graphNode.id,
      type: "workflowGraphNode",
      data: {
        graphNode,
        eventCount: nodeView?.relatedEvents.length ?? 0,
        status: nodeView?.status ?? "unavailable",
      },
      position: {
        x: layout.x,
        y: layout.y,
      },
      className: cn(graphNode.kind === "scatter" && "workflow-graph-scatter-node"),
      extent: graphNode.parentId ? "parent" : undefined,
      parentId: graphNode.parentId ?? undefined,
      selected: graphNode.id === selectedNodeId,
      style: {
        height: layout.height,
        width: layout.width,
      },
    };
  });

  return {
    edges: graph.edges.map(toReactFlowEdge),
    nodes,
  };
}

function toReactFlowEdge(edge: WorkflowGraphEdge): Edge {
  const color = getEdgeColor(edge.kind);
  const label = shouldShowEdgeLabel(edge) ? edge.label : undefined;

  return {
    id: edge.id,
    source: edge.source,
    target: edge.target,
    label,
    labelBgBorderRadius: 4,
    labelBgPadding: [4, 2],
    labelBgStyle: {
      fill: "#ffffff",
      fillOpacity: 0.92,
    },
    labelShowBg: Boolean(label),
    labelStyle: {
      fill: "#334155",
      fontSize: 10,
      fontWeight: 600,
    },
    markerEnd: {
      color,
      type: MarkerType.ArrowClosed,
    },
    style: {
      stroke: color,
      strokeOpacity: edge.kind === "input" ? 0.78 : 0.92,
      strokeWidth: 2,
    },
    type: "smoothstep",
    zIndex: edge.kind === "output" ? 3 : edge.kind === "dependency" ? 2 : 1,
  };
}

function calculateNodeLayouts(graph: WorkflowGraph): Map<string, NodeLayout> {
  const levels = calculateNodeLevels(graph);
  const nodeById = new Map(graph.nodes.map((node) => [node.id, node]));
  const childrenByParent = new Map<string, WorkflowGraphNode[]>();
  const topLevelNodes = graph.nodes.filter((node) => {
    if (!node.parentId) {
      return true;
    }

    const children = childrenByParent.get(node.parentId) ?? [];
    children.push(node);
    childrenByParent.set(node.parentId, children);
    return false;
  });
  const topLevelByColumn = new Map<number, WorkflowGraphNode[]>();

  for (const node of topLevelNodes) {
    const column = levels.get(node.id) ?? 0;
    const nodesInColumn = topLevelByColumn.get(column) ?? [];
    nodesInColumn.push(node);
    topLevelByColumn.set(column, nodesInColumn);
  }

  const layouts = new Map<string, NodeLayout>();
  const columns = [...topLevelByColumn.keys()].sort((left, right) => left - right);

  for (const column of columns) {
    const nodesInColumn = topLevelByColumn.get(column) ?? [];
    let y = 0;
    for (const node of nodesInColumn) {
      const children = childrenByParent.get(node.id) ?? [];
      const isScatter = node.kind === "scatter";
      const height = isScatter
        ? Math.max(220, SCATTER_HEADER_HEIGHT + children.length * (CHILD_NODE_HEIGHT + CHILD_NODE_GAP))
        : TOP_LEVEL_NODE_HEIGHT;
      const width = isScatter ? SCATTER_NODE_WIDTH : TOP_LEVEL_NODE_WIDTH;
      const sourceCenterY = getIncomingSourceCenterY(node.id, graph, layouts, nodeById);

      if (sourceCenterY !== null) {
        y = Math.max(y, sourceCenterY - height / 2);
      }

      layouts.set(node.id, {
        height,
        width,
        x: column * COLUMN_GAP,
        y,
      });

      children.forEach((child, index) => {
        layouts.set(child.id, {
          height: CHILD_NODE_HEIGHT,
          width: CHILD_NODE_WIDTH,
          x: CHILD_NODE_X,
          y: CHILD_NODE_Y + index * (CHILD_NODE_HEIGHT + CHILD_NODE_GAP),
        });
      });

      y += height + ROW_GAP;
    }
  }

  alignWorkflowInputs(graph, layouts, nodeById);

  return layouts;
}

function calculateNodeLevels(graph: WorkflowGraph): Map<string, number> {
  const levels = new Map<string, number>(
    graph.nodes.map((node) => [node.id, node.parentId ? 1 : 0]),
  );
  const parentByNodeId = new Map(graph.nodes.map((node) => [node.id, node.parentId]));

  for (let index = 0; index < graph.nodes.length; index += 1) {
    let changed = false;

    for (const edge of graph.edges) {
      const sourceParent = parentByNodeId.get(edge.source);
      const targetParent = parentByNodeId.get(edge.target);
      const sourceId = sourceParent ?? edge.source;
      const targetId = targetParent ?? edge.target;

      if (sourceId === targetId) {
        continue;
      }

      const nextLevel = (levels.get(sourceId) ?? 0) + 1;
      if (nextLevel > (levels.get(targetId) ?? 0)) {
        levels.set(targetId, nextLevel);
        changed = true;
      }
    }

    if (!changed) {
      break;
    }
  }

  return levels;
}

function alignWorkflowInputs(
  graph: WorkflowGraph,
  layouts: Map<string, NodeLayout>,
  nodeById: Map<string, WorkflowGraphNode>,
): void {
  const inputNodes = graph.nodes
    .filter((node) => node.kind === "workflow-input" && node.parentId === null)
    .map((node, index) => ({
      desiredCenterY: getOutgoingTargetCenterY(node.id, graph, layouts, nodeById),
      index,
      node,
    }))
    .sort((left, right) => {
      const leftY = left.desiredCenterY ?? Number.MAX_SAFE_INTEGER;
      const rightY = right.desiredCenterY ?? Number.MAX_SAFE_INTEGER;
      return leftY - rightY || left.index - right.index;
    });

  let nextY = 0;
  for (const { desiredCenterY, node } of inputNodes) {
    const layout = layouts.get(node.id);
    if (!layout) {
      continue;
    }

    const desiredY = desiredCenterY === null ? nextY : desiredCenterY - layout.height / 2;
    layout.y = Math.max(0, nextY, desiredY);
    nextY = layout.y + layout.height + ROW_GAP;
  }
}

function getIncomingSourceCenterY(
  nodeId: string,
  graph: WorkflowGraph,
  layouts: Map<string, NodeLayout>,
  nodeById: Map<string, WorkflowGraphNode>,
): number | null {
  const centers = graph.edges
    .filter((edge) => edge.target === nodeId)
    .map((edge) => getAbsoluteCenterY(edge.source, layouts, nodeById))
    .filter((center): center is number => center !== null);

  return average(centers);
}

function getOutgoingTargetCenterY(
  nodeId: string,
  graph: WorkflowGraph,
  layouts: Map<string, NodeLayout>,
  nodeById: Map<string, WorkflowGraphNode>,
): number | null {
  const centers = graph.edges
    .filter((edge) => edge.source === nodeId)
    .map((edge) => getAbsoluteCenterY(edge.target, layouts, nodeById))
    .filter((center): center is number => center !== null);

  return average(centers);
}

function getAbsoluteCenterY(
  nodeId: string,
  layouts: Map<string, NodeLayout>,
  nodeById: Map<string, WorkflowGraphNode>,
): number | null {
  const layout = getAbsoluteLayout(nodeId, layouts, nodeById);
  return layout ? layout.y + layout.height / 2 : null;
}

function getAbsoluteLayout(
  nodeId: string,
  layouts: Map<string, NodeLayout>,
  nodeById: Map<string, WorkflowGraphNode>,
): NodeLayout | null {
  const layout = layouts.get(nodeId);
  const node = nodeById.get(nodeId);
  if (!layout || !node) {
    return null;
  }

  if (!node.parentId) {
    return layout;
  }

  const parentLayout = getAbsoluteLayout(node.parentId, layouts, nodeById);
  if (!parentLayout) {
    return null;
  }

  return {
    ...layout,
    x: parentLayout.x + layout.x,
    y: parentLayout.y + layout.y,
  };
}

function average(values: number[]): number | null {
  if (!values.length) {
    return null;
  }

  return values.reduce((total, value) => total + value, 0) / values.length;
}

function getNodeStatus(
  relatedEvents: RunEvent[],
  runStatus: RunStatus,
): WorkflowGraphNodeStatus {
  if (!relatedEvents.length) {
    return runStatus === "running" ? "pending" : "unavailable";
  }

  const latestEvent = relatedEvents[relatedEvents.length - 1];
  const payloadStatus = readPayloadString(latestEvent.payload, "status");

  if (latestEvent.type === "node.failed" || payloadStatus === "failed") {
    return "failed";
  }
  if (latestEvent.type === "node.started") {
    return "running";
  }
  if (latestEvent.type === "node.completed" || payloadStatus === "succeeded") {
    return "completed";
  }

  return "pending";
}

function eventBelongsToNode(event: RunEvent, node: WorkflowGraphNode): boolean {
  const identifiers = new Set([node.id, node.label, node.sourceStepId]);

  if (event.node && identifiers.has(event.node)) {
    return true;
  }

  return [
    "call_id",
    "input_id",
    "node_id",
    "output_id",
    "source_step_id",
    "step_id",
    "workflow_node_id",
  ].some((key) => {
    const value = readPayloadString(event.payload, key);
    return value !== null && identifiers.has(value);
  });
}

function getEdgeColor(kind: WorkflowGraphEdge["kind"]): string {
  if (kind === "input") {
    return "#0f766e";
  }
  if (kind === "output") {
    return "#7c3aed";
  }
  return "#2563eb";
}

function shouldShowEdgeLabel(edge: WorkflowGraphEdge): boolean {
  return edge.kind !== "input";
}

function getMiniMapColor(node: WorkflowGraphReactNode): string {
  if (node.data.status === "failed") {
    return "#ef4444";
  }
  if (node.data.status === "running") {
    return "#2563eb";
  }
  if (node.data.status === "completed") {
    return "#0f766e";
  }
  return "#94a3b8";
}
