"use client";

import { Activity, FileJson, Layers3, SquareTerminal } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { useMemo, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { DiagnosticReport, JsonObject, WorkflowArtifacts } from "@/lib/types";

type ArtifactTabId = "plan" | "ir" | "wdl" | "diagnostics";

type ArtifactTab = {
  id: ArtifactTabId;
  label: string;
  description: string;
  icon: LucideIcon;
};

const artifactTabs: ArtifactTab[] = [
  { id: "plan", label: "Plan", description: "Recipe Tool Plan", icon: FileJson },
  { id: "ir", label: "IR", description: "Workflow DAG 契约", icon: Layers3 },
  { id: "wdl", label: "WDL", description: "生成的 WDL 1.0", icon: SquareTerminal },
  { id: "diagnostics", label: "Diagnostics", description: "Analyzer 与 checker 输出", icon: Activity },
];

function hasJsonContent(value: JsonObject | null): boolean {
  return value !== null && Object.keys(value).length > 0;
}

function formatJson(value: JsonObject | null): string {
  if (!hasJsonContent(value)) {
    return "";
  }
  return JSON.stringify(value, null, 2);
}

function DiagnosticsView({ diagnostics }: { diagnostics: DiagnosticReport }) {
  return (
    <div className="grid gap-4">
      <div className="grid gap-3 sm:grid-cols-4">
        <div className="rounded-md border bg-white p-3">
          <div className="text-xs text-muted-foreground">分析错误</div>
          <div className="mt-1 text-lg font-semibold">{diagnostics.analysis_errors.length}</div>
        </div>
        <div className="rounded-md border bg-white p-3">
          <div className="text-xs text-muted-foreground">分析警告</div>
          <div className="mt-1 text-lg font-semibold">{diagnostics.analysis_warnings.length}</div>
        </div>
        <div className="rounded-md border bg-white p-3">
          <div className="text-xs text-muted-foreground">修复记录</div>
          <div className="mt-1 text-lg font-semibold">{diagnostics.repair_actions.length}</div>
        </div>
        <div className="rounded-md border bg-white p-3">
          <div className="text-xs text-muted-foreground">WDL 校验</div>
          <div className="mt-1 text-sm font-semibold">
            {!diagnostics.check_performed
              ? "未校验"
              : diagnostics.is_valid
                ? "通过"
                : "未通过"}
          </div>
        </div>
      </div>

      <div className="rounded-md border bg-white p-4">
        <div className="text-sm font-semibold">校验信息</div>
        <p className="mt-2 break-words text-sm leading-6 text-muted-foreground">
          {diagnostics.validation_message || "暂无校验信息。"}
        </p>
      </div>

      {diagnostics.analysis_errors.length ? (
        <div className="rounded-md border border-destructive/40 bg-white p-4">
          <div className="text-sm font-semibold text-destructive">分析错误</div>
          <ul className="mt-3 grid gap-2 text-sm leading-6 text-muted-foreground">
            {diagnostics.analysis_errors.map((error) => (
              <li key={error} className="break-words">
                {error}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {diagnostics.analysis_warnings.length ? (
        <div className="rounded-md border bg-white p-4">
          <div className="text-sm font-semibold">分析警告</div>
          <ul className="mt-3 grid gap-2 text-sm leading-6 text-muted-foreground">
            {diagnostics.analysis_warnings.map((warning) => (
              <li key={warning} className="break-words">
                {warning}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {diagnostics.repair_actions.length ? (
        <div className="rounded-md border bg-white p-4">
          <div className="text-sm font-semibold">修复记录</div>
          <ul className="mt-3 grid gap-2 text-sm leading-6 text-muted-foreground">
            {diagnostics.repair_actions.map((action) => (
              <li key={action} className="break-words">
                {action}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export function RunArtifactsPanel({
  artifacts,
  diagnostics,
}: {
  artifacts: WorkflowArtifacts;
  diagnostics: DiagnosticReport;
}) {
  const [activeTab, setActiveTab] = useState<ArtifactTabId>("plan");
  const content = useMemo(
    () => ({
      plan: formatJson(artifacts.plan),
      ir: formatJson(artifacts.workflow_ir),
      wdl: artifacts.wdl,
    }),
    [artifacts.plan, artifacts.workflow_ir, artifacts.wdl],
  );

  const active = artifactTabs.find((tab) => tab.id === activeTab) ?? artifactTabs[0];

  return (
    <section className="mt-6 rounded-md border bg-white p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="font-semibold">结构化产物</h2>
            <Badge variant="outline">{active.description}</Badge>
          </div>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Plan、Workflow IR、WDL 与诊断来自持久化 run snapshot。
          </p>
        </div>
        <div className="flex flex-wrap gap-2" aria-label="Run artifacts">
          {artifactTabs.map((tab) => (
            <Button
              key={tab.id}
              type="button"
              variant={activeTab === tab.id ? "secondary" : "outline"}
              size="sm"
              aria-pressed={activeTab === tab.id}
              onClick={() => setActiveTab(tab.id)}
            >
              <tab.icon className="h-4 w-4" />
              {tab.label}
            </Button>
          ))}
        </div>
      </div>

      <div className="mt-5 rounded-md border bg-background p-4">
        {activeTab === "diagnostics" ? (
          <DiagnosticsView diagnostics={diagnostics} />
        ) : content[activeTab] ? (
          <pre className="max-h-[42rem] overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-6 text-foreground">
            {content[activeTab]}
          </pre>
        ) : (
          <div className="text-sm leading-6 text-muted-foreground">当前 run 尚未产生该产物。</div>
        )}
      </div>
    </section>
  );
}
