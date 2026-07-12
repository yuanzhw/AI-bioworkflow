import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  CircleDashed,
  Clock3,
  FileText,
  Layers3,
  RotateCcw,
  XCircle,
} from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { RunArtifactsPanel } from "@/components/run/run-artifacts-panel";
import { RunEventsTimeline } from "@/components/run/run-events-timeline";
import { RunFailureSummary } from "@/components/run/run-failure-summary";
import { WorkflowGraphPanel } from "@/components/workflow-graph/workflow-graph";
import { getRunSnapshot } from "@/lib/api";
import type { JsonObject, RunStatus, WorkflowRunSnapshotResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

const statusLabels: Record<RunStatus, string> = {
  created: "已创建",
  running: "运行中",
  succeeded: "成功",
  failed: "失败",
};

const kindLabels: Record<string, string> = {
  natural_language: "自然语言",
  structured_compile: "结构化编译",
};

const detailDateTimeFormat = new Intl.DateTimeFormat("zh-CN", {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

function getStatusBadgeVariant(status: RunStatus): "secondary" | "destructive" | "outline" {
  if (status === "failed") {
    return "destructive";
  }
  if (status === "succeeded") {
    return "secondary";
  }
  return "outline";
}

function getStatusIcon(status: RunStatus) {
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

function formatDateTime(value: string | null): string {
  if (!value) {
    return "未记录";
  }
  return detailDateTimeFormat.format(new Date(value));
}

function formatRequest(request: string | JsonObject | null): string {
  if (request === null) {
    return "暂无请求内容。";
  }
  if (typeof request === "string") {
    return request;
  }
  return JSON.stringify(request, null, 2);
}

function getRequestLabel(request: string | JsonObject | null): string {
  if (request === null) {
    return "未记录";
  }
  return typeof request === "string" ? "Natural-language request" : "Structured payload";
}

function formatError(error: unknown): string {
  console.error("Failed to load run detail.", error);
  return "Run 详情暂时无法读取，请确认 FastAPI 服务正在运行，或从历史列表重新进入。";
}

function StatItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border bg-background p-4">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className="mt-2 break-words text-sm font-semibold">{value}</div>
    </div>
  );
}

function DiagnosticsSummary({ snapshot }: { snapshot: WorkflowRunSnapshotResponse }) {
  const diagnostics = snapshot.diagnostics;
  const validationLabel = !diagnostics.check_performed
    ? "未校验"
    : diagnostics.is_valid
      ? "WDL valid"
      : "校验未通过";

  return (
    <div className="grid gap-3 md:grid-cols-4">
      <StatItem label="分析错误" value={String(diagnostics.analysis_errors.length)} />
      <StatItem label="分析警告" value={String(diagnostics.analysis_warnings.length)} />
      <StatItem label="修复记录" value={String(diagnostics.repair_actions.length)} />
      <StatItem label="校验状态" value={validationLabel} />
    </div>
  );
}

function RunDetail({ snapshot }: { snapshot: WorkflowRunSnapshotResponse }) {
  const kindLabel = snapshot.kind ? kindLabels[snapshot.kind] ?? snapshot.kind : "未记录";
  const requestText = formatRequest(snapshot.request);

  return (
    <>
      <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div className="max-w-3xl">
          <div className="flex flex-wrap gap-3">
            <Badge variant={getStatusBadgeVariant(snapshot.status)} className="gap-1.5">
              {getStatusIcon(snapshot.status)}
              {statusLabels[snapshot.status]}
            </Badge>
            <Badge variant="outline">{kindLabel}</Badge>
            <Badge variant="secondary">W5 详情回放</Badge>
          </div>
          <h1 className="mt-4 break-words text-3xl font-semibold tracking-normal">
            Run 详情回放
          </h1>
          <p className="mt-3 break-all font-mono text-sm leading-6 text-muted-foreground">
            {snapshot.run_id}
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button asChild variant="outline">
            <Link href="/runs">
              <ArrowLeft className="h-4 w-4" />
              返回历史
            </Link>
          </Button>
          <Button asChild>
            <Link href="/workspace?example=rnaseq-deg">
              <RotateCcw className="h-4 w-4" />
              运行示例
            </Link>
          </Button>
        </div>
      </div>

      <section className="grid gap-3 md:grid-cols-4">
        <StatItem label="创建时间" value={formatDateTime(snapshot.created_at)} />
        <StatItem label="更新时间" value={formatDateTime(snapshot.updated_at)} />
        <StatItem label="完成时间" value={formatDateTime(snapshot.completed_at)} />
        <StatItem label="运行类型" value={kindLabel} />
      </section>

      <section className="mt-6 rounded-md border bg-white p-5">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <div className="flex items-center gap-2">
              <FileText className="h-5 w-5 text-primary" />
              <h2 className="font-semibold">请求内容</h2>
            </div>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              {getRequestLabel(snapshot.request)}
            </p>
          </div>
          {snapshot.artifacts.workflow_ir && Object.keys(snapshot.artifacts.workflow_ir).length ? (
            <Badge variant="outline" className="gap-1.5">
              <Layers3 className="h-3.5 w-3.5" />
              Workflow IR 已保存
            </Badge>
          ) : null}
        </div>
        <pre className="mt-5 max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md border bg-background p-4 font-mono text-xs leading-6">
          {requestText}
        </pre>
      </section>

      <section className="mt-6 rounded-md border bg-white p-5">
        <div className="mb-5 flex items-center gap-2">
          <AlertCircle className="h-5 w-5 text-primary" />
          <h2 className="font-semibold">诊断摘要</h2>
        </div>
        <DiagnosticsSummary snapshot={snapshot} />
      </section>

      {snapshot.status === "failed" ? (
        <RunFailureSummary
          artifacts={snapshot.artifacts}
          className="mt-6"
          diagnostics={snapshot.diagnostics}
        />
      ) : null}

      <WorkflowGraphPanel workflowIr={snapshot.artifacts.workflow_ir} />
      <RunEventsTimeline eventsUrl={snapshot.events_url} status={snapshot.status} />
      <RunArtifactsPanel artifacts={snapshot.artifacts} diagnostics={snapshot.diagnostics} />
    </>
  );
}

export default async function RunDetailPage({
  params,
}: {
  params: Promise<{ runId: string }>;
}) {
  const { runId } = await params;
  let snapshot: WorkflowRunSnapshotResponse | null = null;
  let errorMessage: string | null = null;

  try {
    snapshot = await getRunSnapshot(runId);
  } catch (error) {
    errorMessage = formatError(error);
  }

  return (
    <div className="mx-auto max-w-7xl px-6 py-8 sm:px-8 lg:px-10">
      {snapshot ? (
        <RunDetail snapshot={snapshot} />
      ) : (
        <div>
          <Button asChild variant="ghost" className="mb-8 px-0">
            <Link href="/runs">
              <ArrowLeft className="h-4 w-4" />
              返回历史
            </Link>
          </Button>
          <div className="rounded-md border border-destructive/40 bg-white p-6">
            <div className="flex items-center gap-2 font-semibold text-destructive">
              <AlertCircle className="h-5 w-5" />
              Run 详情读取失败
            </div>
            <p className="mt-3 break-words text-sm leading-6 text-muted-foreground">
              {errorMessage}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
