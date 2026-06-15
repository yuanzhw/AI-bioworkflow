"use client";

import {
  AlertCircle,
  CheckCircle2,
  Clock3,
  FileText,
  Loader2,
  Play,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { createStructuredCompileRun, getRunSnapshot } from "@/lib/api";
import { rnaseqRecipePlan } from "@/lib/examples";
import type { RunAcceptedResponse, RunStatus, WorkflowRunSnapshotResponse } from "@/lib/types";

const POLL_INTERVAL_MS = 1200;

function isTerminalRunStatus(status: RunStatus): boolean {
  return status === "succeeded" || status === "failed";
}

function getRunStatusLabel(status: RunStatus): string {
  const labels: Record<RunStatus, string> = {
    created: "已创建",
    running: "运行中",
    succeeded: "成功",
    failed: "失败",
  };
  return labels[status];
}

function formatRunError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "请求处理失败，请稍后重试。";
}

function getStatusIcon(status: RunStatus, isPolling: boolean) {
  if (isPolling && !isTerminalRunStatus(status)) {
    return <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />;
  }
  if (status === "succeeded") {
    return <CheckCircle2 className="mr-1 h-3.5 w-3.5" />;
  }
  if (status === "failed") {
    return <XCircle className="mr-1 h-3.5 w-3.5" />;
  }
  return <Clock3 className="mr-1 h-3.5 w-3.5" />;
}

function getStatusBadgeVariant(status: RunStatus): "secondary" | "destructive" | "outline" {
  if (status === "failed") {
    return "destructive";
  }
  if (status === "succeeded") {
    return "secondary";
  }
  return "outline";
}

export function WorkspaceRunLauncher() {
  const [acceptedRun, setAcceptedRun] = useState<RunAcceptedResponse | null>(null);
  const [snapshot, setSnapshot] = useState<WorkflowRunSnapshotResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [pollErrorMessage, setPollErrorMessage] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isPolling, setIsPolling] = useState(false);

  useEffect(() => {
    if (acceptedRun === null) {
      return undefined;
    }

    const runId = acceptedRun.run_id;
    let timeoutId: number | undefined;
    let isCancelled = false;

    async function pollSnapshot() {
      setIsPolling(true);

      try {
        const nextSnapshot = await getRunSnapshot(runId);
        if (isCancelled) {
          return;
        }

        setSnapshot(nextSnapshot);
        setPollErrorMessage(null);

        if (!isTerminalRunStatus(nextSnapshot.status)) {
          timeoutId = window.setTimeout(pollSnapshot, POLL_INTERVAL_MS);
        }
      } catch (error) {
        if (isCancelled) {
          return;
        }

        setPollErrorMessage(formatRunError(error));
        timeoutId = window.setTimeout(pollSnapshot, POLL_INTERVAL_MS * 2);
      } finally {
        if (!isCancelled) {
          setIsPolling(false);
        }
      }
    }

    void pollSnapshot();

    return () => {
      isCancelled = true;
      if (timeoutId !== undefined) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [acceptedRun]);

  const currentStatus = snapshot?.status ?? acceptedRun?.status ?? null;
  const wdlLineCount = useMemo(() => {
    if (!snapshot?.artifacts.wdl) {
      return 0;
    }
    return snapshot.artifacts.wdl.split(/\r?\n/).filter(Boolean).length;
  }, [snapshot?.artifacts.wdl]);

  async function handleRunExample() {
    setIsSubmitting(true);
    setErrorMessage(null);
    setPollErrorMessage(null);
    setSnapshot(null);

    try {
      const accepted = await createStructuredCompileRun(rnaseqRecipePlan, true);
      setAcceptedRun(accepted);
    } catch (error) {
      setAcceptedRun(null);
      setSnapshot(null);
      setErrorMessage(formatRunError(error));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex w-full flex-col gap-2 sm:w-auto sm:items-end">
      <Button type="button" onClick={handleRunExample} disabled={isSubmitting}>
        {isSubmitting ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Play className="h-4 w-4" />
        )}
        {isSubmitting ? "提交中" : acceptedRun ? "重新运行示例" : "运行示例"}
      </Button>

      {acceptedRun && currentStatus ? (
        <div className="w-full max-w-md rounded-md border bg-background p-3 text-xs leading-5 sm:text-right">
          <div className="flex flex-wrap items-center gap-2 sm:justify-end">
            <Badge variant={getStatusBadgeVariant(currentStatus)}>
              {getStatusIcon(currentStatus, isPolling)}
              {getRunStatusLabel(currentStatus)}
            </Badge>
            <span className="break-all font-mono text-muted-foreground">{acceptedRun.run_id}</span>
          </div>

          <div className="mt-2 grid gap-1 text-muted-foreground sm:justify-items-end">
            <div className="max-w-full break-words">
              WDL：
              {snapshot?.artifacts.wdl ? `${wdlLineCount} 行，${snapshot.artifacts.wdl.length} 字符` : "等待生成"}
            </div>
            <div className="max-w-full break-words">
              校验：
              {snapshot?.diagnostics.validation_message || "等待 checker 结果"}
            </div>
            {snapshot?.diagnostics.analysis_errors.length ? (
              <div className="text-destructive">
                分析错误：{snapshot.diagnostics.analysis_errors.length} 条
              </div>
            ) : null}
            {snapshot?.diagnostics.repair_actions.length ? (
              <div>修复记录：{snapshot.diagnostics.repair_actions.length} 条</div>
            ) : null}
          </div>

          <div className="mt-2 flex items-center gap-1 text-muted-foreground sm:justify-end">
            <FileText className="h-3.5 w-3.5" />
            <span>完整 Plan / IR / WDL tabs 将在后续切片接入。</span>
          </div>
        </div>
      ) : null}

      {pollErrorMessage ? (
        <div className="flex max-w-md items-start gap-2 text-xs leading-5 text-destructive sm:text-right">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 flex-none" />
          <span>Run 状态查询失败：{pollErrorMessage}</span>
        </div>
      ) : null}

      {errorMessage ? (
        <div className="flex max-w-md items-start gap-2 text-xs leading-5 text-destructive sm:text-right">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 flex-none" />
          <span>{errorMessage}</span>
        </div>
      ) : null}
    </div>
  );
}
