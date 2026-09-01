import { ArrowLeft, CheckCircle2, Container, Database, RotateCcw, ShieldCheck } from "lucide-react";
import type { Metadata } from "next";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiDocsUrl } from "@/lib/api";
import { rnaseqDemoWorkspaceHref, rnaseqRecipeSteps } from "@/lib/examples";

export const metadata: Metadata = {
  title: "Recipe and Tool Catalog",
  description:
    "Inspect the approved recipe, tool schemas, command contracts, runtime containers, and execution-verification boundaries.",
  alternates: {
    canonical: "/catalog",
  },
  openGraph: {
    type: "website",
    title: "Recipe and Tool Catalog",
    description:
      "Inspect the approved recipe, tool schemas, command contracts, runtime containers, and execution-verification boundaries.",
    url: "/catalog",
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
    title: "Recipe and Tool Catalog",
    description:
      "Inspect the approved recipe, tool schemas, command contracts, runtime containers, and execution-verification boundaries.",
    images: ["/og.png"],
  },
};

const tools = [
  ["fastp", "读段质量控制", "quay.io/biocontainers/fastp", "e2e-validated"],
  ["salmon", "转录本定量", "quay.io/biocontainers/salmon", "e2e-validated"],
  ["tximport", "基因层面汇总", "项目维护镜像", "e2e-validated"],
  ["deseq2", "差异表达分析", "项目维护镜像", "e2e-validated"],
  ["multiqc", "质控报告汇总", "项目维护镜像", "e2e-validated"],
];

export default function CatalogPage() {
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
            <Badge variant="secondary">Catalog trust boundary</Badge>
            <Badge variant="outline">RNA-seq 示例</Badge>
          </div>
          <h1 className="mt-4 text-3xl font-semibold tracking-normal">Recipe 与 Tool Catalog 预览</h1>
          <p className="mt-3 leading-7 text-muted-foreground">
            Catalog 是生信步骤、准入工具、命令模板、输出 schema 和 runtime container 的正式边界。
            当前页面用 RNA-seq DEG 示例解释目录契约；工作台和历史页会展示这些边界如何约束 Plan、IR 和 WDL。
          </p>
        </div>
        <Button asChild variant="outline">
          <Link href={rnaseqDemoWorkspaceHref}>
            <RotateCcw className="h-4 w-4" />
            运行 RNA-seq 示例
          </Link>
        </Button>
      </div>

      <div className="grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
        <section className="rounded-md border bg-white p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 font-semibold">
              <Database className="h-5 w-5 text-primary" />
              RNA-seq DEG recipe
            </div>
            <Badge variant="outline">静态 recipe 示例</Badge>
          </div>
          <div className="mt-5 grid gap-3">
            {rnaseqRecipeSteps.map((step, index) => (
              <div key={step} className="flex items-center justify-between gap-4 rounded-md border bg-background p-4">
                <div>
                  <div className="text-sm font-semibold text-primary">0{index + 1}</div>
                  <div className="mt-1 font-medium">{step}</div>
                </div>
                <Badge variant="outline">必需步骤</Badge>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-md border bg-white p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2 font-semibold">
              <ShieldCheck className="h-5 w-5 text-primary" />
              已准入工具
            </div>
            <Badge variant="outline">静态 tool 示例</Badge>
          </div>
          <div className="mt-5 grid gap-3">
            {tools.map(([tool, role, runtime, verification]) => (
              <div key={tool} className="rounded-md border bg-background p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="font-semibold">{tool}</div>
                  <div className="flex flex-wrap gap-2">
                    <Badge variant="secondary">catalog-approved</Badge>
                    <Badge variant="outline">{verification}</Badge>
                  </div>
                </div>
                <div className="mt-2 text-sm text-muted-foreground">{role}</div>
                <div className="mt-3 flex items-center gap-2 text-xs text-muted-foreground">
                  <Container className="h-3.5 w-3.5 text-primary" />
                  {runtime}
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="mt-6 rounded-md border bg-white p-5">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="font-semibold">Catalog 页面边界</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              页面只解释 Catalog 契约；工具选择、命令模板和容器来源仍由后端 Catalog 约束。
            </p>
          </div>
          <Button asChild variant="outline">
            <Link href={apiDocsUrl}>查看 API 契约</Link>
          </Button>
        </div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {[
            ["schema", "inputs、outputs、parameters 和 command templates 都是显式定义。"],
            ["runtime", "编译后的 WDL 使用 catalog 声明的 container。"],
            ["admission", "catalog-approved 只表示工具已进入正式 Catalog。"],
            ["verification", "执行状态独立显示为 unverified、smoke-tested 或 e2e-validated。"],
          ].map(([label, detail]) => (
            <div key={label} className="flex gap-3 rounded-md border bg-background p-4">
              <CheckCircle2 className="mt-0.5 h-5 w-5 flex-none text-primary" />
              <div>
                <div className="font-semibold">{label}</div>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">{detail}</p>
              </div>
            </div>
          ))}
        </div>
        <div className="mt-5 grid gap-3 md:grid-cols-2">
          <div className="rounded-md border bg-background p-4">
            <div className="font-semibold text-primary">当前已实现</div>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              展示 RNA-seq recipe steps、Catalog 准入、runtime 和独立 execution verification 状态。
            </p>
          </div>
          <div className="rounded-md border bg-background p-4">
            <div className="font-semibold text-primary">API contract</div>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              `/api/recipes` 和 `/api/tools` 保留为 Catalog 查询入口；前端不推断或替换工具定义。
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
