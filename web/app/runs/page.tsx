import {
  AlertCircle,
  ArrowLeft,
  CheckCircle2,
  CircleDashed,
  Clock3,
  Eye,
  History,
  Loader2,
  RotateCcw,
  XCircle,
} from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiDocsUrl, formatApiError, listRuns } from "@/lib/api";
import { rnaseqDemoWorkspaceHref } from "@/lib/examples";
import type { RunListResponse, RunStatus, RunSummary } from "@/lib/types";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Run History",
  description:
    "Review replayable compiler runs, validation outcomes, artifacts, diagnostics, and Workflow IR DAGs.",
  alternates: {
    canonical: "/runs",
  },
  openGraph: {
    type: "website",
    title: "Run History",
    description:
      "Review replayable compiler runs, validation outcomes, artifacts, diagnostics, and Workflow IR DAGs.",
    url: "/runs",
    images: [
      {
        url: "/og.png",
        width: 1280,
        height: 640,
        alt: "AI-bioworkflow catalog-bound planning to validated WDL",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Run History",
    description:
      "Review replayable compiler runs, validation outcomes, artifacts, diagnostics, and Workflow IR DAGs.",
    images: ["/og.png"],
  },
};

const PAGE_SIZE = 20;
const statusFilters: Array<{ label: string; value: RunStatus | "all" }> = [
  { label: "全部", value: "all" },
  { label: "运行中", value: "running" },
  { label: "成功", value: "succeeded" },
  { label: "失败", value: "failed" },
  { label: "已创建", value: "created" },
];

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

const runListDateTimeFormat = new Intl.DateTimeFormat("zh-CN", {
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

function isRunStatus(value: string | undefined): value is RunStatus {
  return value === "created" || value === "running" || value === "succeeded" || value === "failed";
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

function getStatusIcon(status: RunStatus) {
  if (status === "succeeded") {
    return <CheckCircle2 className="h-4 w-4" />;
  }
  if (status === "failed") {
    return <XCircle className="h-4 w-4" />;
  }
  if (status === "running") {
    return <Loader2 className="h-4 w-4 animate-spin" />;
  }
  return <CircleDashed className="h-4 w-4" />;
}

function getValidationLabel(run: RunSummary): string {
  if (!run.diagnostic_summary.check_performed) {
    return "未校验";
  }
  if (run.status === "created" || run.status === "running") {
    return "等待校验";
  }
  return run.diagnostic_summary.is_valid ? "WDL valid" : "校验未通过";
}

function formatDateTime(value: string | null): string {
  if (!value) {
    return "未完成";
  }
  return runListDateTimeFormat.format(new Date(value));
}

function formatError(error: unknown): string {
  console.error("Failed to load run history.", error);
  return formatApiError(error, "Run 历史记录暂时无法读取，请确认 FastAPI 服务正在运行后重试。");
}

function buildRunsHref(status: RunStatus | "all", page = 1): string {
  const params = new URLSearchParams();
  if (status !== "all") {
    params.set("status", status);
  }
  if (page > 1) {
    params.set("page", String(page));
  }
  const query = params.toString();
  return query ? `/runs?${query}` : "/runs";
}

function parsePage(value: string | undefined): number {
  const parsed = Number.parseInt(value ?? "1", 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 1;
}

function RunRow({ run }: { run: RunSummary }) {
  const diagnostic = run.diagnostic_summary;

  return (
    <div className="grid gap-4 rounded-md border bg-background p-4 lg:grid-cols-[minmax(0,1.2fr)_auto_auto_auto] lg:items-center">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={getStatusBadgeVariant(run.status)} className="gap-1.5">
            {getStatusIcon(run.status)}
            {statusLabels[run.status]}
          </Badge>
          <Badge variant="outline">{kindLabels[run.kind] ?? run.kind}</Badge>
        </div>
        <div className="mt-3 break-words font-medium">
          {run.request_summary ?? "无请求摘要"}
        </div>
        <div className="mt-2 break-all font-mono text-xs text-muted-foreground">
          {run.run_id}
        </div>
      </div>

      <div className="grid gap-2 text-sm text-muted-foreground sm:grid-cols-4 lg:min-w-[28rem]">
        <div>
          <div className="text-xs">错误</div>
          <div className="mt-1 font-medium text-foreground">{diagnostic.analysis_error_count}</div>
        </div>
        <div>
          <div className="text-xs">警告</div>
          <div className="mt-1 font-medium text-foreground">{diagnostic.analysis_warning_count}</div>
        </div>
        <div>
          <div className="text-xs">修复</div>
          <div className="mt-1 font-medium text-foreground">{diagnostic.repair_action_count}</div>
        </div>
        <div>
          <div className="text-xs">校验</div>
          <div className="mt-1 font-medium text-foreground">{getValidationLabel(run)}</div>
        </div>
      </div>

      <div className="text-sm text-muted-foreground lg:text-right">
        <div className="flex items-center gap-2 lg:justify-end">
          <Clock3 className="h-4 w-4 text-primary" />
          {formatDateTime(run.updated_at)}
        </div>
        <div className="mt-2 text-xs">创建 {formatDateTime(run.created_at)}</div>
        <div className="mt-1 text-xs">完成 {formatDateTime(run.completed_at)}</div>
      </div>

      <Button asChild variant="outline" size="sm">
        <Link href={`/runs/${encodeURIComponent(run.run_id)}`}>
          <Eye className="h-4 w-4" />
          查看详情
        </Link>
      </Button>
    </div>
  );
}

function RunsList({
  firstPageHref,
  response,
}: {
  firstPageHref: string;
  response: RunListResponse;
}) {
  if (response.runs.length === 0) {
    if (response.total > 0) {
      return (
        <div className="rounded-md border bg-background p-6">
          <div className="flex items-center gap-2 font-semibold">
            <History className="h-5 w-5 text-primary" />
            当前页没有记录
          </div>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            该筛选条件下共有 {response.total} 条 run，但当前分页已超出结果范围。
          </p>
          <Button asChild className="mt-5" variant="outline">
            <Link href={firstPageHref}>返回第一页</Link>
          </Button>
        </div>
      );
    }

    return (
      <div className="rounded-md border bg-background p-6">
        <div className="flex items-center gap-2 font-semibold">
          <History className="h-5 w-5 text-primary" />
          暂无历史记录
        </div>
        <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
          运行一次 RNA-seq 示例后，这里会显示持久化 run 摘要。
        </p>
        <Button asChild className="mt-5">
          <Link href={rnaseqDemoWorkspaceHref}>
            <RotateCcw className="h-4 w-4" />
            打开工作台
          </Link>
        </Button>
      </div>
    );
  }

  return (
    <div className="grid gap-3">
      {response.runs.map((run) => (
        <RunRow key={run.run_id} run={run} />
      ))}
    </div>
  );
}

export default async function RunsPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string; page?: string }>;
}) {
  const params = await searchParams;
  const status = isRunStatus(params.status) ? params.status : undefined;
  const selectedFilter = status ?? "all";
  const page = parsePage(params.page);
  const offset = (page - 1) * PAGE_SIZE;

  let runList: RunListResponse | null = null;
  let errorMessage: string | null = null;

  try {
    runList = await listRuns({
      limit: PAGE_SIZE,
      offset,
      status,
    });
  } catch (error) {
    errorMessage = formatError(error);
  }

  const hasPreviousPage = page > 1;
  const hasNextPage = runList ? runList.offset + runList.runs.length < runList.total : false;

  return (
    <div className="mx-auto max-w-7xl px-6 py-8 sm:px-8 lg:px-10">
      <Button asChild variant="ghost" className="mb-8 px-0">
        <Link href="/">
          <ArrowLeft className="h-4 w-4" />
          返回首页
        </Link>
      </Button>

      <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
        <div className="max-w-3xl">
          <div className="flex flex-wrap gap-3">
            <Badge variant="secondary">Replayable run history</Badge>
            <Badge variant="outline">持久化编译记录</Badge>
          </div>
          <h1 className="mt-4 text-3xl font-semibold tracking-normal">Run 回放与审计</h1>
          <p className="mt-3 leading-7 text-muted-foreground">
            历史列表读取持久化 run 摘要，保留状态、请求摘要、诊断计数和时间戳。记录成功表示编译与 WDL 校验通过，不表示默认执行工具容器。
          </p>
        </div>
        <Button asChild variant="outline">
          <Link href={rnaseqDemoWorkspaceHref}>
            <RotateCcw className="h-4 w-4" />
            运行 RNA-seq 示例
          </Link>
        </Button>
      </div>

      <section>
        <div className="flex flex-col gap-4 border-b pb-5 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-2 font-semibold">
            <History className="h-5 w-5 text-primary" />
            Run 历史
          </div>
          <div className="flex flex-wrap gap-2">
            {statusFilters.map((filter) => (
              <Button
                key={filter.value}
                asChild
                variant={selectedFilter === filter.value ? "secondary" : "outline"}
                size="sm"
              >
                <Link href={buildRunsHref(filter.value)}>{filter.label}</Link>
              </Button>
            ))}
          </div>
        </div>

        <div className="mt-5 flex flex-wrap items-center gap-3 text-sm text-muted-foreground">
          {runList ? <Badge variant="outline">{runList.total} 条记录</Badge> : null}
          {status ? <span>当前筛选：{statusLabels[status]}</span> : <span>当前筛选：全部</span>}
        </div>

        <div className="mt-5">
          {errorMessage ? (
            <div className="rounded-md border border-destructive/40 bg-background p-5">
              <div className="flex items-center gap-2 font-semibold text-destructive">
                <AlertCircle className="h-5 w-5" />
                历史记录读取失败
              </div>
              <p className="mt-2 break-words text-sm leading-6 text-muted-foreground">{errorMessage}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button asChild size="sm">
                  <Link href={rnaseqDemoWorkspaceHref}>
                    <RotateCcw className="h-4 w-4" />
                    运行示例
                  </Link>
                </Button>
                <Button asChild variant="outline" size="sm">
                  <Link href={apiDocsUrl}>查看 API 文档</Link>
                </Button>
              </div>
            </div>
          ) : runList ? (
            <RunsList firstPageHref={buildRunsHref(selectedFilter)} response={runList} />
          ) : null}
        </div>

        {runList && (hasPreviousPage || hasNextPage) ? (
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t pt-5">
            <div className="text-sm text-muted-foreground">第 {page} 页</div>
            <div className="flex gap-2">
              {hasPreviousPage ? (
                <Button asChild variant="outline" size="sm">
                  <Link href={buildRunsHref(selectedFilter, Math.max(1, page - 1))}>上一页</Link>
                </Button>
              ) : (
                <Button variant="outline" size="sm" disabled>
                  上一页
                </Button>
              )}
              {hasNextPage ? (
                <Button asChild variant="outline" size="sm">
                  <Link href={buildRunsHref(selectedFilter, page + 1)}>下一页</Link>
                </Button>
              ) : (
                <Button variant="outline" size="sm" disabled>
                  下一页
                </Button>
              )}
            </div>
          </div>
        ) : null}
      </section>
    </div>
  );
}
