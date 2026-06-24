"use client";

import {
  AlertCircle,
  CheckCircle2,
  CircleDashed,
  Clock3,
  Loader2,
  XCircle,
} from "lucide-react";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { buildRunEventsUrl } from "@/lib/api";
import {
  isTerminalRunStatus,
  mergeRunEvent,
  parseRunEventMessage,
  runEventLabels,
  runEventTypes,
} from "@/lib/run-events";
import type { RunEvent, RunStatus } from "@/lib/types";

const eventDateTimeFormat = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

function getEventIcon(event: RunEvent) {
  if (event.type === "node.failed" || event.payload.status === "failed") {
    return <XCircle className="h-4 w-4 text-destructive" />;
  }
  if (
    event.type === "node.completed" ||
    event.type === "validation.completed" ||
    event.type === "run.completed"
  ) {
    return <CheckCircle2 className="h-4 w-4 text-primary" />;
  }
  if (event.type === "node.started") {
    return <Loader2 className="h-4 w-4 animate-spin text-primary" />;
  }
  return <CircleDashed className="h-4 w-4 text-muted-foreground" />;
}

function formatDateTime(value: string): string {
  return eventDateTimeFormat.format(new Date(value));
}

export function RunEventsTimeline({
  eventsUrl,
  status,
}: {
  eventsUrl: string | null;
  status: RunStatus;
}) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [streamError, setStreamError] = useState<string | null>(null);
  const [isConnected, setIsConnected] = useState(false);

  useEffect(() => {
    if (!eventsUrl) {
      return undefined;
    }

    const eventSource = new EventSource(buildRunEventsUrl(eventsUrl));

    eventSource.onopen = () => {
      setIsConnected(true);
      setStreamError(null);
    };

    eventSource.onerror = () => {
      setIsConnected(false);
      setStreamError("事件流暂时不可用，请稍后刷新。");
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
          setIsConnected(false);
          eventSource.close();
        }
      };
      eventSource.addEventListener(eventType, handler);
      return { eventType, handler };
    });

    return () => {
      handlers.forEach(({ eventType, handler }) => {
        eventSource.removeEventListener(eventType, handler);
      });
      eventSource.close();
    };
  }, [eventsUrl, status]);

  return (
    <section className="mt-6 rounded-md border bg-white p-5">
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h2 className="font-semibold">事件时间线</h2>
            <Badge variant="outline">{events.length} 条事件</Badge>
          </div>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            事件来自持久化 SSE envelope，可用于回放 run 的关键阶段。
          </p>
        </div>
        <Badge variant={isConnected ? "secondary" : "outline"} className="gap-1.5">
          {isConnected ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Clock3 className="h-3.5 w-3.5" />}
          {isConnected ? "读取事件" : isTerminalRunStatus(status) ? "已完成" : "等待连接"}
        </Badge>
      </div>

      {streamError ? (
        <div className="mt-4 flex items-start gap-2 rounded-md border border-destructive/40 bg-background p-4 text-sm text-destructive">
          <AlertCircle className="mt-0.5 h-4 w-4 flex-none" />
          <span>{streamError}</span>
        </div>
      ) : null}

      {events.length ? (
        <div className="mt-5 grid gap-3">
          {events.map((event) => (
            <div key={event.event_id} className="grid gap-3 rounded-md border bg-background p-4 md:grid-cols-[auto_minmax(0,1fr)_auto] md:items-start">
              <div className="mt-0.5">{getEventIcon(event)}</div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant="outline">#{event.sequence}</Badge>
                  <span className="font-medium">{runEventLabels[event.type]}</span>
                  {event.node ? <Badge variant="secondary">{event.node}</Badge> : null}
                </div>
                <p className="mt-2 break-words text-sm leading-6 text-muted-foreground">
                  {event.summary}
                </p>
              </div>
              <div className="text-xs text-muted-foreground md:text-right">
                {formatDateTime(event.timestamp)}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="mt-5 rounded-md border bg-background p-5 text-sm leading-6 text-muted-foreground">
          暂无事件回放。
        </div>
      )}
    </section>
  );
}
