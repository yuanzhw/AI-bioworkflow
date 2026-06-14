import { ArrowLeft, CheckCircle2, Container, Database, ShieldCheck } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiDocsUrl } from "@/lib/api";
import { rnaseqRecipeSteps } from "@/lib/examples";

const tools = [
  ["fastp", "读段质量控制", "quay.io/biocontainers/fastp"],
  ["salmon", "转录本定量", "quay.io/biocontainers/salmon"],
  ["tximport", "基因层面汇总", "项目维护镜像"],
  ["deseq2", "差异表达分析", "项目维护镜像"],
  ["multiqc", "质控报告汇总", "项目维护镜像"],
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

      <div className="mb-8 max-w-3xl">
        <div className="flex flex-wrap gap-3">
          <Badge variant="secondary">W3 静态预览</Badge>
          <Badge variant="outline">示例数据</Badge>
        </div>
        <h1 className="mt-4 text-3xl font-semibold tracking-normal">Recipe 与 Tool Catalog 预览</h1>
        <p className="mt-3 leading-7 text-muted-foreground">
          Catalog 是生信步骤、准入工具、命令模板、输出 schema 和 runtime container 的正式边界。
          当前页面使用 RNA-seq 示例说明目录页的信息结构；真实 recipe / tool 数据会在后续从
          FastAPI catalog endpoints 读取。
        </p>
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
            {tools.map(([tool, role, runtime]) => (
              <div key={tool} className="rounded-md border bg-background p-4">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="font-semibold">{tool}</div>
                  <Badge variant="secondary">catalog-approved</Badge>
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
              W3 先固定页面信息架构，避免把工具选择逻辑放进前端。
            </p>
          </div>
          <Button asChild variant="outline">
            <Link href={apiDocsUrl}>查看 API 契约</Link>
          </Button>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {[
            ["schema", "inputs、outputs、parameters 和 command templates 都是显式定义。"],
            ["runtime", "编译后的 WDL 使用 catalog 声明的 container。"],
            ["trust", "工具记录会暴露 catalog-approved 或 experimental 状态。"],
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
              展示 RNA-seq recipe steps、准入工具、runtime 和 trust status 的前端呈现方式。
            </p>
          </div>
          <div className="rounded-md border bg-background p-4">
            <div className="font-semibold text-primary">后续接入</div>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              从 `/api/recipes` 和 `/api/tools` 读取真实 catalog，并支持工具详情页。
            </p>
          </div>
        </div>
      </section>
    </div>
  );
}
