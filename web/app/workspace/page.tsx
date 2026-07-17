import { ArrowLeft, BookOpen, History } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { apiDocsUrl } from "@/lib/api";
import { rnaseqDemoExampleSlug, rnaseqExamplePrompt } from "@/lib/examples";
import { WorkspaceWorkbench } from "./workspace-workbench";

export default async function WorkspacePage({
  searchParams,
}: {
  searchParams: Promise<{ example?: string }>;
}) {
  const params = await searchParams;
  const isExample = params.example === rnaseqDemoExampleSlug;

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
            <Badge variant="secondary">W5 Workbench</Badge>
            <Badge variant="outline">真实 run 接入</Badge>
          </div>
          <p className="mt-3 max-w-2xl text-muted-foreground">
            提交结构化示例或自然语言请求后，工作台会订阅事件流、轮询 snapshot，并展示同一次 run
            的 Plan、Workflow IR、WDL 和 diagnostics。
          </p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button asChild variant="outline">
            <Link href="/runs">
              <History className="h-4 w-4" />
              Run 历史回放
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link href={apiDocsUrl}>
              <BookOpen className="h-4 w-4" />
              API 文档
            </Link>
          </Button>
        </div>
      </div>

      <WorkspaceWorkbench
        initialMode={isExample ? "structured" : "natural_language"}
        initialRequest={isExample ? rnaseqExamplePrompt : ""}
      />
    </div>
  );
}
