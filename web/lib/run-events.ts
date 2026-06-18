import type { JsonObject, RunEvent, RunEventType, RunStatus } from "@/lib/types";

export const runEventTypes: RunEventType[] = [
  "run.created",
  "node.started",
  "node.completed",
  "node.failed",
  "artifact.updated",
  "repair.applied",
  "validation.completed",
  "run.completed",
];

export const runEventLabels: Record<RunEventType, string> = {
  "run.created": "Run 创建",
  "node.started": "节点开始",
  "node.completed": "节点完成",
  "node.failed": "节点失败",
  "artifact.updated": "产物更新",
  "repair.applied": "修复应用",
  "validation.completed": "校验完成",
  "run.completed": "Run 完成",
};

export function isTerminalRunStatus(status: RunStatus): boolean {
  return status === "succeeded" || status === "failed";
}

export function mergeRunEvent(events: RunEvent[], nextEvent: RunEvent): RunEvent[] {
  const bySequence = new Map(events.map((event) => [event.sequence, event]));
  bySequence.set(nextEvent.sequence, nextEvent);
  return Array.from(bySequence.values()).sort((left, right) => left.sequence - right.sequence);
}

export function parseRunEventMessage(message: MessageEvent<string>): RunEvent | null {
  try {
    const parsed: unknown = JSON.parse(message.data);
    if (!isRecord(parsed)) {
      return null;
    }

    const { event_id, node, payload, run_id, sequence, summary, timestamp, type } = parsed;
    if (
      typeof event_id !== "string" ||
      typeof run_id !== "string" ||
      typeof sequence !== "number" ||
      !Number.isInteger(sequence) ||
      sequence < 1 ||
      !isRunEventType(type) ||
      typeof timestamp !== "string" ||
      Number.isNaN(Date.parse(timestamp)) ||
      typeof summary !== "string" ||
      !(node === null || typeof node === "string") ||
      !isRecord(payload)
    ) {
      return null;
    }

    return {
      event_id,
      run_id,
      sequence,
      type,
      timestamp,
      summary,
      node,
      payload: payload as JsonObject,
    };
  } catch (error) {
    console.error("Failed to parse run event.", error);
    return null;
  }
}

export function readPayloadString(payload: JsonObject, key: string): string | null {
  const value = payload[key];
  return typeof value === "string" ? value : null;
}

function isRunEventType(value: unknown): value is RunEventType {
  return typeof value === "string" && runEventTypes.includes(value as RunEventType);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
