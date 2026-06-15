import {
  Activity,
  ArrowLeft,
  CheckCircle2,
  CircleDashed,
  Clock3,
  FileJson,
  Layers3,
  SquareTerminal,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiDocsUrl } from "@/lib/api";
import { rnaseqExamplePrompt, rnaseqRecipeSteps } from "@/lib/examples";
import { WorkspaceRunLauncher } from "./workspace-run-launcher";

const timeline = [
  ["需求输入", "request", "展示自然语言请求和预期 recipe steps"],
  ["结构化规划", "planner", "预留 Recipe Tool Plan review 位置"],
  ["IR 标准化", "normalizer", "预留 Workflow IR 审阅位置"],
  ["静态分析", "analyzer", "展示 Analyzer 诊断和保守修复记录"],
  ["WDL 渲染", "renderer", "展示确定性 Renderer 生成的 WDL"],
  ["语法校验", "checker", "展示 WOMtool 或 miniwdl 校验结果"],
];

const artifactTabs: Array<{
  label: string;
  description: string;
  icon: LucideIcon;
}> = [
  { label: "Plan", description: "Recipe Tool Plan", icon: FileJson },
  { label: "IR", description: "Workflow DAG 契约", icon: Layers3 },
  { label: "WDL", description: "生成的 WDL 1.0", icon: SquareTerminal },
  { label: "Diagnostics", description: "Analyzer 与 checker 输出", icon: Activity },
];

export default async function WorkspacePage({
  searchParams,
}: {
  searchParams: Promise<{ example?: string }>;
}) {
  const params = await searchParams;
  const isExample = params.example === "rnaseq-deg";
  const requestText = isExample ? rnaseqExamplePrompt : "在这里描述一个工作流需求。";

  return (
    <div className="mx-auto max-w-7xl px-6 py-8 sm:px-8 lg:px-10">
      <div className="mb-8 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
        <div>
          <Button asChild variant="ghost" className="mb-4 px-0">
            <Link href="/">
              <ArrowLeft className="h-4 w-4" />
              返回首页
            </Link>
          </Button>
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-3xl font-semibold tracking-normal">Workflow 工作台</h1>
            <Badge variant="secondary">W4 初版</Badge>
          </div>
          <p className="mt-3 max-w-2xl text-muted-foreground">
            当前已可提交 RNA-seq 结构化示例 run，轮询 snapshot，并显示 run 状态、WDL
            摘要和校验结果。SSE 时间线与完整 Plan / IR / WDL / Diagnostics tabs 会在后续切片接入。
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <WorkspaceRunLauncher />
          <Button asChild variant="outline">
            <Link href={apiDocsUrl}>API 文档</Link>
          </Button>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-[0.85fr_1.15fr]">
        <section className="rounded-md border bg-white p-5">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="font-semibold">请求输入</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                运行按钮会提交结构化 Recipe Tool Plan 示例；前端不生成 IR 或 WDL。
              </p>
            </div>
            <Badge variant={isExample ? "default" : "outline"}>
              {isExample ? "RNA-seq 示例" : "空白请求"}
            </Badge>
          </div>
          <div className="mt-5 rounded-md border bg-background p-4 font-mono text-sm leading-6">
            {requestText}
          </div>
          <div className="mt-5">
            <h3 className="text-sm font-semibold">预期 recipe steps</h3>
            <div className="mt-3 flex flex-wrap gap-2">
              {rnaseqRecipeSteps.map((step) => (
                <Badge key={step} variant="outline">
                  {step}
                </Badge>
              ))}
            </div>
          </div>
        </section>

        <section className="rounded-md border bg-white p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="font-semibold">Run 时间线</h2>
              <p className="mt-1 text-sm text-muted-foreground">
                当前展示目标事件结构；下一切片会从持久化 SSE event envelope 实时更新。
              </p>
            </div>
            <Badge variant="outline">
              <Clock3 className="mr-1 h-3.5 w-3.5" />
              SSE 待接入
            </Badge>
          </div>
          <div className="mt-5 grid gap-3 md:grid-cols-2">
            {timeline.map(([title, node, summary], index) => (
              <div key={node} className="rounded-md border bg-background p-4">
                <div className="flex items-center gap-2">
                  {index < 3 ? (
                    <CheckCircle2 className="h-4 w-4 text-primary" />
                  ) : (
                    <CircleDashed className="h-4 w-4 text-muted-foreground" />
                  )}
                  <span className="text-sm font-semibold">{title}</span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{node}</p>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{summary}</p>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="mt-6 rounded-md border bg-white p-5">
        <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div>
            <h2 className="font-semibold">结构化产物</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              当前先固定产物区的信息架构，并在运行卡片中读取同一次 run 的 WDL 与 diagnostics 摘要。
              完整 Plan、IR、WDL 和 Diagnostics tabs 会在后续切片接入。
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            {artifactTabs.map((tab) => (
              <div key={tab.label} className="rounded-md border bg-background px-3 py-2 text-sm">
                <div className="flex items-center gap-2 font-semibold">
                  <tab.icon className="h-4 w-4 text-primary" />
                  {tab.label}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">{tab.description}</div>
              </div>
            ))}
          </div>
        </div>
        <div className="mt-5 grid gap-4 lg:grid-cols-[0.9fr_1.1fr]">
          <div className="rounded-md border bg-background p-4">
            <div className="text-sm font-semibold text-primary">编译契约</div>
            <pre className="mt-4 overflow-x-auto whitespace-pre-wrap font-mono text-xs leading-6 text-foreground">
{`{
  "recipe": "rnaseq_differential_expression",
  "tool_calls": ["fastp", "salmon", "tximport", "deseq2", "multiqc"],
  "target": "Workflow IR -> WDL 1.0"
}`}
            </pre>
          </div>
          <div className="rounded-md border bg-background p-4">
            <div className="text-sm font-semibold text-primary">诊断信息入口</div>
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              {[
                "分析错误 (analysis_errors)",
                "修复记录 (repair_actions)",
                "校验信息 (validation_message)",
              ].map((item) => (
                <div key={item} className="rounded-md border bg-white p-3 text-sm">
                  <div className="font-medium">{item}</div>
                  <div className="mt-2 text-muted-foreground">等待完整 tabs 接入</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
