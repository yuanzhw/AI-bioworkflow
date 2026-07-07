import {
  Activity,
  AlertCircle,
  FileJson,
  GitBranch,
  SquareTerminal,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import type { DiagnosticReport, JsonObject, WorkflowArtifacts } from "@/lib/types";
import { cn } from "@/lib/utils";

type ArtifactState = {
  badge: string;
  badgeVariant: "outline" | "secondary";
  description: string;
  icon: LucideIcon;
  label: string;
};

function hasJsonContent(value: JsonObject | null): boolean {
  return value !== null && Object.keys(value).length > 0;
}

function hasWdlContent(value: string): boolean {
  return value.trim().length > 0;
}

function hasDiagnosticSignals(diagnostics: DiagnosticReport): boolean {
  return (
    diagnostics.analysis_errors.length > 0 ||
    diagnostics.analysis_warnings.length > 0 ||
    diagnostics.repair_actions.length > 0 ||
    diagnostics.validation_message.trim().length > 0 ||
    diagnostics.check_performed
  );
}

function getPrimaryFailureReason(diagnostics: DiagnosticReport): string {
  const analysisError = diagnostics.analysis_errors.find((error) => error.trim().length > 0);
  if (analysisError) {
    return analysisError;
  }

  const validationMessage = diagnostics.validation_message.trim();
  if (validationMessage) {
    return validationMessage;
  }

  const analysisWarning = diagnostics.analysis_warnings.find(
    (warning) => warning.trim().length > 0,
  );
  if (analysisWarning) {
    return analysisWarning;
  }

  return "Run 未成功完成，但 diagnostics 中没有记录具体错误；请查看事件时间线中的失败事件。";
}

function getDagDisplayMessage(artifacts: WorkflowArtifacts): string {
  if (hasJsonContent(artifacts.workflow_ir)) {
    return "DAG 展示失败前已经保存的 Workflow IR 结构；失败阶段以事件时间线和 diagnostics 为准，不映射成 workflow call 执行状态。";
  }

  if (hasJsonContent(artifacts.plan)) {
    return "Plan 已保存，但 run 在产生 Workflow IR 前失败；DAG 暂不可用，优先查看事件时间线和 diagnostics。";
  }

  return "Run 在保存 Workflow IR 前失败；DAG 暂不可用，优先查看事件时间线和 diagnostics。";
}

function getArtifactStates(
  artifacts: WorkflowArtifacts,
  diagnostics: DiagnosticReport,
): ArtifactState[] {
  const hasPlan = hasJsonContent(artifacts.plan);
  const hasWorkflowIr = hasJsonContent(artifacts.workflow_ir);
  const hasWdl = hasWdlContent(artifacts.wdl);
  const hasDiagnostics = hasDiagnosticSignals(diagnostics);

  return [
    {
      badge: hasPlan ? "已保留" : "未产生",
      badgeVariant: hasPlan ? "secondary" : "outline",
      description: "Recipe Tool Plan",
      icon: FileJson,
      label: "Plan",
    },
    {
      badge: hasWorkflowIr ? "已保留" : "未产生",
      badgeVariant: hasWorkflowIr ? "secondary" : "outline",
      description: "DAG 可视化输入",
      icon: GitBranch,
      label: "Workflow IR",
    },
    {
      badge: hasWdl ? "已保留" : "未产生",
      badgeVariant: hasWdl ? "secondary" : "outline",
      description: "Renderer 输出",
      icon: SquareTerminal,
      label: "WDL",
    },
    {
      badge: hasDiagnostics ? "有线索" : "空报告",
      badgeVariant: hasDiagnostics ? "secondary" : "outline",
      description: "Analyzer 与 checker 记录",
      icon: Activity,
      label: "Diagnostics",
    },
  ];
}

export function RunFailureSummary({
  artifacts,
  className,
  diagnostics,
}: {
  artifacts: WorkflowArtifacts;
  className?: string;
  diagnostics: DiagnosticReport;
}) {
  const primaryFailureReason = getPrimaryFailureReason(diagnostics);
  const dagDisplayMessage = getDagDisplayMessage(artifacts);
  const artifactStates = getArtifactStates(artifacts, diagnostics);

  return (
    <section className={cn("rounded-md border border-destructive/40 bg-white p-5", className)}>
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <AlertCircle className="h-5 w-5 text-destructive" />
            <h2 className="font-semibold">失败回放</h2>
          </div>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Run 未成功完成；这里汇总持久化 snapshot 中保留下来的失败线索和结构化产物。
          </p>
        </div>
        <Badge variant="destructive">运行失败</Badge>
      </div>

      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <div className="rounded-md border bg-background p-4">
          <div className="text-sm font-semibold">首要失败线索</div>
          <p className="mt-2 break-words text-sm leading-6 text-muted-foreground">
            {primaryFailureReason}
          </p>
        </div>
        <div className="rounded-md border bg-background p-4">
          <div className="text-sm font-semibold">DAG 展示口径</div>
          <p className="mt-2 break-words text-sm leading-6 text-muted-foreground">
            {dagDisplayMessage}
          </p>
        </div>
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {artifactStates.map((artifact) => (
          <div key={artifact.label} className="rounded-md border bg-background p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2">
                <artifact.icon className="h-4 w-4 flex-none text-primary" />
                <div className="truncate text-sm font-semibold">{artifact.label}</div>
              </div>
              <Badge variant={artifact.badgeVariant}>{artifact.badge}</Badge>
            </div>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              {artifact.description}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}
