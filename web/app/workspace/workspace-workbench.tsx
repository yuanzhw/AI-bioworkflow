"use client";

import {
  AlertCircle,
  CheckCircle2,
  CircleDashed,
  Clock3,
  FileText,
  Loader2,
  Play,
  RotateCcw,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { RunArtifactsPanel } from "@/components/run/run-artifacts-panel";
import { RunEventsTimeline } from "@/components/run/run-events-timeline";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  createNaturalLanguageRun,
  createStructuredCompileRun,
  getRunSnapshot,
} from "@/lib/api";
import { rnaseqExamplePrompt, rnaseqRecipePlan, rnaseqRecipeSteps } from "@/lib/examples";
import type {
  DiagnosticReport,
  RunAcceptedResponse,
  RunStatus,
  WorkflowArtifacts,
  WorkflowRunSnapshotResponse,
} from "@/lib/types";
import { cn } from "@/lib/utils";

type WorkspaceRunMode = "structured" | "natural_language";

const POLL_INTERVAL_MS = 1200;

const emptyArtifacts: WorkflowArtifacts = {
  plan: null,
  workflow_ir: {},
  wdl: "",
  extras: {},
  manifest: [],
};

const emptyDiagnostics: DiagnosticReport = {
  analysis_errors: [],
  analysis_warnings: [],
  repair_actions: [],
  validation_message: "",
  is_valid: false,
  succeeded: false,
  check_performed: false,
};

const runModeOptions: Array<{
  description: string;
  label: string;
  value: WorkspaceRunMode;
}> = [
  {
    description: "不依赖 planner 环境，适合稳定展示编译链路。",
    label: "结构化示例",
    value: "structured",
  },
  {
    description: "调用自然语言 planner，失败诊断保存在同一次 run。",
    label: "自然语言",
    value: "natural_language",
  },
];

const statusLabels: Record<RunStatus, string> = {
  created: "已创建",
  running: "运行中",
  succeeded: "成功",
  failed: "失败",
};

function isTerminalRunStatus(status: RunStatus): boolean {
  return status === "succeeded" || status === "failed";
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

function getStatusIcon(status: RunStatus, isPolling: boolean) {
  if (isPolling && !isTerminalRunStatus(status)) {
    return <Loader2 className="h-4 w-4 animate-spin" />;
  }
  if (status === "succeeded") {
    return <CheckCircle2 className="h-4 w-4" />;
  }
  if (status === "failed") {
    return <XCircle className="h-4 w-4" />;
  }
  if (status === "running") {
    return <Clock3 className="h-4 w-4" />;
  }
  return <CircleDashed className="h-4 w-4" />;
}

function formatRunError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "请求处理失败，请稍后重试。";
}

function validationLabel(diagnostics: DiagnosticReport): string {
  if (!diagnostics.check_performed) {
    return "未校验";
  }
  if (diagnostics.is_valid) {
    return "WDL valid";
  }
  return "校验未通过";
}

function StatTile({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border bg-background p-3">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-1 break-words text-sm font-semibold">{value}</div>
    </div>
  );
}

export function WorkspaceWorkbench({
  initialMode,
  initialRequest,
}: {
  initialMode: WorkspaceRunMode;
  initialRequest: string;
}) {
  const [mode, setMode] = useState<WorkspaceRunMode>(initialMode);
  const [requestText, setRequestText] = useState(initialRequest);
  const [plannerModel, setPlannerModel] = useState("");
  const [check, setCheck] = useState(true);
  const [acceptedRun, setAcceptedRun] = useState<RunAcceptedResponse | null>(null);
  const [snapshot, setSnapshot] = useState<WorkflowRunSnapshotResponse | null>(null);
  const [submitErrorMessage, setSubmitErrorMessage] = useState<string | null>(null);
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

  const currentStatus = snapshot?.status ?? acceptedRun?.status ?? "created";
  const artifacts = snapshot?.artifacts ?? emptyArtifacts;
  const diagnostics = snapshot?.diagnostics ?? emptyDiagnostics;
  const wdlLineCount = useMemo(() => {
    if (!artifacts.wdl) {
      return 0;
    }
    return artifacts.wdl.split(/\r?\n/).filter(Boolean).length;
  }, [artifacts.wdl]);

  function handleModeChange(nextMode: WorkspaceRunMode) {
    setMode(nextMode);
    if (nextMode === "structured" && !requestText.trim()) {
      setRequestText(rnaseqExamplePrompt);
    }
  }

  async function handleRun() {
    setIsSubmitting(true);
    setAcceptedRun(null);
    setSnapshot(null);
    setSubmitErrorMessage(null);
    setPollErrorMessage(null);

    try {
      const accepted =
        mode === "structured"
          ? await createStructuredCompileRun(rnaseqRecipePlan, check)
          : await createNaturalLanguageRun(
              requestText.trim(),
              check,
              plannerModel.trim() || undefined,
            );
      setAcceptedRun(accepted);
    } catch (error) {
      setSubmitErrorMessage(formatRunError(error));
    } finally {
      setIsSubmitting(false);
    }
  }

  const runButtonDisabled =
    isSubmitting || (mode === "natural_language" && requestText.trim().length === 0);

  return (
    <>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
        <section className="rounded-md border bg-white p-5">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div>
              <h2 className="font-semibold">请求与运行模式</h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                工作台提交后端 run，并展示同一次 run 的事件、产物与诊断。
              </p>
            </div>
            <Badge variant={mode === "structured" ? "default" : "outline"}>
              {mode === "structured" ? "RNA-seq 示例" : "Planner run"}
            </Badge>
          </div>

          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            {runModeOptions.map((option) => (
              <button
                key={option.value}
                type="button"
                aria-pressed={mode === option.value}
                className={cn(
                  "rounded-md border bg-background p-4 text-left transition-colors hover:bg-muted",
                  mode === option.value && "border-primary bg-secondary",
                )}
                onClick={() => handleModeChange(option.value)}
              >
                <div className="font-semibold">{option.label}</div>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  {option.description}
                </p>
              </button>
            ))}
          </div>

          <label className="mt-5 block text-sm font-semibold" htmlFor="workflow-request">
            自然语言请求
          </label>
          <textarea
            id="workflow-request"
            className="mt-2 min-h-44 w-full resize-y rounded-md border bg-background p-4 text-sm leading-6 outline-none focus-visible:ring-2 focus-visible:ring-ring"
            value={requestText}
            onChange={(event) => setRequestText(event.target.value)}
            placeholder="描述一个需要规划和编译的生信工作流。"
          />

          <div className="mt-4 grid gap-4 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
            {mode === "natural_language" ? (
              <div>
                <label className="block text-sm font-semibold" htmlFor="planner-model">
                  Planner model
                </label>
                <input
                  id="planner-model"
                  className="mt-2 h-10 w-full rounded-md border bg-background px-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  value={plannerModel}
                  onChange={(event) => setPlannerModel(event.target.value)}
                  placeholder="使用后端默认模型"
                />
              </div>
            ) : (
              <div>
                <div className="text-sm font-semibold">Recipe steps</div>
                <div className="mt-2 flex flex-wrap gap-2">
                  {rnaseqRecipeSteps.map((step) => (
                    <Badge key={step} variant="outline">
                      {step}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            <label className="inline-flex items-center gap-2 rounded-md border bg-background px-3 py-2 text-sm">
              <input
                type="checkbox"
                className="h-4 w-4 accent-primary"
                checked={check}
                onChange={(event) => setCheck(event.target.checked)}
              />
              WDL syntax check
            </label>
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-3">
            <Button type="button" onClick={handleRun} disabled={runButtonDisabled}>
              {isSubmitting ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Play className="h-4 w-4" />
              )}
              {isSubmitting ? "提交中" : acceptedRun ? "重新运行" : "运行"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => {
                setRequestText(rnaseqExamplePrompt);
                setMode("structured");
              }}
            >
              <RotateCcw className="h-4 w-4" />
              RNA-seq 示例
            </Button>
            {acceptedRun ? (
              <Button asChild variant="outline">
                <Link href={`/runs/${encodeURIComponent(acceptedRun.run_id)}`}>
                  <FileText className="h-4 w-4" />
                  查看详情
                </Link>
              </Button>
            ) : null}
          </div>

          {submitErrorMessage ? (
            <div className="mt-4 flex items-start gap-2 rounded-md border border-destructive/40 bg-background p-4 text-sm text-destructive">
              <AlertCircle className="mt-0.5 h-4 w-4 flex-none" />
              <span className="break-words">{submitErrorMessage}</span>
            </div>
          ) : null}
        </section>

        <section className="rounded-md border bg-white p-5">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div>
              <h2 className="font-semibold">当前 run</h2>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                状态、校验和产物摘要随 snapshot 轮询更新。
              </p>
            </div>
            <Badge variant={getStatusBadgeVariant(currentStatus)} className="gap-1.5">
              {getStatusIcon(currentStatus, isPolling)}
              {acceptedRun ? statusLabels[currentStatus] : "未创建"}
            </Badge>
          </div>

          <div className="mt-5 rounded-md border bg-background p-4">
            <div className="text-xs text-muted-foreground">Run id</div>
            <div className="mt-2 break-all font-mono text-sm font-semibold">
              {acceptedRun?.run_id ?? "等待提交"}
            </div>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            <StatTile label="运行类型" value={snapshot?.kind ?? (mode === "structured" ? "structured_compile" : "natural_language")} />
            <StatTile label="校验状态" value={validationLabel(diagnostics)} />
            <StatTile label="WDL" value={artifacts.wdl ? `${wdlLineCount} 行` : "等待生成"} />
            <StatTile label="诊断" value={`${diagnostics.analysis_errors.length} errors / ${diagnostics.repair_actions.length} repairs`} />
          </div>

          {pollErrorMessage ? (
            <div className="mt-4 flex items-start gap-2 rounded-md border border-destructive/40 bg-background p-4 text-sm text-destructive">
              <AlertCircle className="mt-0.5 h-4 w-4 flex-none" />
              <span className="break-words">Run 状态查询失败：{pollErrorMessage}</span>
            </div>
          ) : null}

          {diagnostics.validation_message ? (
            <div className="mt-4 rounded-md border bg-background p-4">
              <div className="text-sm font-semibold">校验信息</div>
              <p className="mt-2 break-words text-sm leading-6 text-muted-foreground">
                {diagnostics.validation_message}
              </p>
            </div>
          ) : null}
        </section>
      </div>

      <RunEventsTimeline
        eventsUrl={acceptedRun?.events_url ?? null}
        status={currentStatus}
        title="Run 时间线"
        description="Planner、Compiler Graph、artifact 更新和 checker 事件来自后端 SSE。"
        emptyMessage={acceptedRun ? "等待后端事件。" : "提交 run 后显示事件。"}
      />

      <RunArtifactsPanel
        artifacts={artifacts}
        diagnostics={diagnostics}
        title="Plan / IR / WDL / Diagnostics"
        description="工作台不在前端生成或修复结构化产物；这里展示持久化 snapshot 中保存的真实结果。"
      />
    </>
  );
}
