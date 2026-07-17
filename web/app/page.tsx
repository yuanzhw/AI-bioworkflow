import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Code2,
  Database,
  FileJson,
  FlaskConical,
  GitBranch,
  History,
  Layers3,
  Network,
  ShieldCheck,
  SquareTerminal,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { apiDocsUrl } from "@/lib/api";
import { rnaseqDemoWorkspaceHref, rnaseqExamplePrompt, rnaseqRecipeSteps } from "@/lib/examples";

const pipelineStages = [
  {
    label: "自然语言请求",
    detail: "用户意图先进入规划层，不直接生成最终 WDL。",
  },
  {
    label: "Recipe Tool Plan",
    detail: "Planner 输出受 recipe 和 tool catalog 的结构化 schema 约束。",
  },
  {
    label: "Workflow IR",
    detail: "编译契约记录 steps、calls、scatter 和 workflow outputs。",
  },
  {
    label: "Analyzer / Repairer",
    detail: "渲染前执行静态分析，并只做可确定的保守修复。",
  },
  {
    label: "WDL Renderer",
    detail: "由模板和普通代码从 Workflow IR 生成 WDL 1.0。",
  },
  {
    label: "Checker",
    detail: "通过 WOMtool 或 miniwdl 完成语法校验闭环。",
  },
];

const engineeringBoundaries = [
  {
    title: "LLM 只到规划边界",
    description:
      "模型可以辅助生成结构化 Recipe Tool Plan，但最终 WDL 由确定性编译器代码输出。",
    icon: Code2,
  },
  {
    title: "Catalog 控制工具选择",
    description:
      "Recipe、命令模板、参数、输出、容器镜像和 trust status 都来自正式 catalog 定义。",
    icon: Database,
  },
  {
    title: "验证过程可追踪",
    description:
      "Workflow IR 分析、修复记录和 WDL checker 输出会作为 diagnostics 保留并展示。",
    icon: ShieldCheck,
  },
];

const systemSurfaces: Array<{
  title: string;
  description: string;
  icon: LucideIcon;
}> = [
  {
    title: "Plan JSON",
    description: "展示 recipe、工具选择、参数和 workflow 级输入。",
    icon: FileJson,
  },
  {
    title: "Workflow IR",
    description: "作为编译器和 DAG 可视化共享的规范结构。",
    icon: Layers3,
  },
  {
    title: "校验后的 WDL",
    description: "由 Renderer 生成、可被机器消费的 WDL 1.0。",
    icon: SquareTerminal,
  },
  {
    title: "Diagnostics",
    description: "汇总 Analyzer 发现、repair actions 和 checker messages。",
    icon: Activity,
  },
  {
    title: "Timeline",
    description: "基于持久化 SSE envelope 回放 run 生命周期事件。",
    icon: GitBranch,
  },
  {
    title: "DAG",
    description: "查看 Workflow IR 的 calls、scatter、依赖边和结构状态。",
    icon: Network,
  },
];

const stackRows = [
  ["编译器核心", "Python 3.13、LangGraph、Pydantic、Jinja2"],
  ["API 层", "FastAPI、SQLite run history、SSE 事件回放"],
  ["Web 外壳", "Next.js、TypeScript、Tailwind、React Flow"],
  ["工作流目标", "Workflow IR、WDL 1.0、WOMtool / miniwdl 校验"],
];

export default function Home() {
  const demoRoutes: Array<{
    title: string;
    href: string;
  }> = [
    {
      title: "运行 RNA-seq 示例",
      href: rnaseqDemoWorkspaceHref,
    },
    {
      title: "回看 Run 历史",
      href: "/runs",
    },
    {
      title: "审阅 Catalog 边界",
      href: "/catalog",
    },
  ];
  const demoHighlights = ["Timeline", "Plan / IR / WDL", "Diagnostics", "Workflow IR DAG", "Failed replay"];

  return (
    <div>
      <section className="workflow-backdrop border-b">
        <div className="mx-auto flex min-h-[620px] max-w-7xl flex-col justify-center px-6 py-12 sm:px-8 lg:px-10">
          <div className="w-full max-w-[calc(100vw-3rem)] sm:max-w-2xl">
            <div className="flex flex-wrap items-center gap-3">
              <Badge variant="secondary">Bioinformatics workflow compiler</Badge>
              <Badge variant="outline">W6 portfolio demo hub</Badge>
            </div>
            <h1 className="mt-6 text-4xl font-semibold tracking-normal text-foreground sm:text-5xl lg:text-6xl">
              AI-bioworkflow
            </h1>
            <p className="mt-6 max-w-xl break-words text-base leading-7 text-muted-foreground sm:text-lg sm:leading-8">
              一个把自然语言或结构化生信需求编译成可验证 WDL 的工程作品集：
              LLM 停在 Recipe Tool Plan 边界，Workflow IR、Analyzer、Renderer 和 Checker
              负责确定性的编译闭环。
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Button asChild>
                <Link href={rnaseqDemoWorkspaceHref}>
                  运行 RNA-seq 示例
                  <ArrowRight className="h-4 w-4" />
                </Link>
              </Button>
              <Button asChild variant="outline">
                <Link href="/runs">
                  <History className="h-4 w-4" />
                  Run 历史
                </Link>
              </Button>
              <Button asChild variant="outline">
                <Link href="/catalog">
                  <Database className="h-4 w-4" />
                  Catalog
                </Link>
              </Button>
              <Button asChild variant="outline">
                <Link href={apiDocsUrl}>查看 API 文档</Link>
              </Button>
            </div>

            <div className="mt-7 max-w-2xl rounded-md border bg-white/82 p-3 shadow-sm backdrop-blur">
              <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-sm">
                <div className="flex items-center gap-2 font-semibold text-primary">
                  <FlaskConical className="h-4 w-4 text-accent" />
                  推荐演示路径
                </div>
                <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-muted-foreground">
                  {demoRoutes.map((route, index) => (
                    <span key={route.title} className="inline-flex items-center gap-2">
                      <Link href={route.href} className="font-medium text-foreground hover:text-primary">
                        {index + 1}. {route.title}
                      </Link>
                      {index < demoRoutes.length - 1 ? <ArrowRight className="h-3.5 w-3.5 text-primary/70" /> : null}
                    </span>
                  ))}
                </div>
              </div>
            </div>

            <div className="mt-8 flex max-w-2xl flex-wrap gap-2">
              {demoHighlights.map((item) => (
                <Badge key={item} variant="outline" className="bg-white/80">
                  {item}
                </Badge>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section id="overview" className="border-b bg-white">
        <div className="mx-auto max-w-7xl px-6 py-12 sm:px-8 lg:px-10">
          <div className="mb-7 flex items-center gap-2 text-sm font-medium text-primary">
            <GitBranch className="h-4 w-4" />
            确定性的规划到编译链路
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-6">
            {pipelineStages.map((stage, index) => (
              <div key={stage.label} className="rounded-md border bg-background p-4">
                <div className="text-sm font-semibold text-primary">0{index + 1}</div>
                <div className="mt-3 font-medium">{stage.label}</div>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{stage.detail}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto max-w-7xl px-6 py-14 sm:px-8 lg:px-10">
        <div className="mb-8 max-w-2xl">
          <h2 className="text-2xl font-semibold tracking-normal">工程边界</h2>
          <p className="mt-3 text-muted-foreground">
            页面展示的不是聊天结果，而是 Python service layer 和 compiler graph 真实维护的结构化边界。
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {engineeringBoundaries.map((item) => (
            <Card key={item.title}>
              <CardHeader>
                <div className="mb-4 flex h-9 w-9 items-center justify-center rounded-md bg-secondary text-primary">
                  <item.icon className="h-5 w-5" />
                </div>
                <CardTitle>{item.title}</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm leading-6 text-muted-foreground">{item.description}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <section id="case" className="border-y bg-white">
        <div className="mx-auto grid max-w-7xl gap-8 px-6 py-12 sm:px-8 lg:grid-cols-[0.85fr_1.15fr] lg:px-10">
          <div>
            <div className="flex items-center gap-2 text-sm font-semibold text-primary">
              <FlaskConical className="h-4 w-4 text-accent" />
              RNA-seq 差异表达分析
            </div>
            <h2 className="mt-4 text-2xl font-semibold tracking-normal">一个具体的生信案例</h2>
            <p className="mt-4 leading-7 text-muted-foreground">{rnaseqExamplePrompt}</p>
            <div className="mt-6 flex flex-wrap gap-2">
              {rnaseqRecipeSteps.map((step) => (
                <Badge key={step} variant="outline">
                  {step}
                </Badge>
              ))}
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-5">
            {rnaseqRecipeSteps.map((step, index) => (
              <div key={step} className="rounded-md border bg-background p-4">
                <div className="text-sm font-semibold text-primary">0{index + 1}</div>
                <div className="mt-3 min-h-12 text-sm font-medium leading-6">{step}</div>
                <div className="mt-4 h-1.5 rounded-full bg-secondary">
                  <div className="h-1.5 rounded-full bg-primary" style={{ width: `${35 + index * 13}%` }} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="surfaces" className="mx-auto max-w-7xl px-6 py-14 sm:px-8 lg:px-10">
        <div className="mb-8 flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
          <div className="max-w-2xl">
            <h2 className="text-2xl font-semibold tracking-normal">系统视图</h2>
            <p className="mt-3 text-muted-foreground">
              工作台与历史详情围绕 workflow review 最重要的产物和可观测记录组织。
            </p>
          </div>
          <Button asChild variant="outline">
            <Link href={rnaseqDemoWorkspaceHref}>打开工作台</Link>
          </Button>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {systemSurfaces.map((surface) => (
            <div key={surface.title} className="rounded-md border bg-white p-5">
              <surface.icon className="h-5 w-5 text-primary" />
              <h3 className="mt-4 font-semibold">{surface.title}</h3>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">{surface.description}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="border-t bg-white">
        <div className="mx-auto grid max-w-7xl gap-6 px-6 py-12 sm:px-8 lg:grid-cols-[0.7fr_1.3fr] lg:px-10">
          <div>
            <h2 className="text-2xl font-semibold tracking-normal">技术栈</h2>
            <p className="mt-3 text-muted-foreground">
              Web 层保持轻量并聚焦产品展示，编译器核心继续复用于 CLI 和 API 路径。
            </p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {stackRows.map(([label, body]) => (
              <div key={label} className="flex gap-3 rounded-md border bg-background p-4">
                <CheckCircle2 className="mt-0.5 h-5 w-5 flex-none text-primary" />
                <div>
                  <h3 className="font-semibold">{label}</h3>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">{body}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </div>
  );
}
