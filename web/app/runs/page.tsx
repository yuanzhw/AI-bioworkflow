import { ArrowLeft, CheckCircle2, Clock3, History, RotateCcw, XCircle } from "lucide-react";
import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

const runStates = [
  ["succeeded", "成功样例", "RNA-seq DEG 示例", "Plan、IR、WDL、diagnostics 已归档"],
  ["running", "流式样例", "自然语言 workflow 请求", "Timeline 事件正在追加"],
  ["failed", "失败样例", "无效 recipe 输入", "诊断报告与错误阶段已保留"],
];

const stateIcon = {
  succeeded: CheckCircle2,
  running: Clock3,
  failed: XCircle,
};

export default function RunsPage() {
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
            <Badge variant="secondary">W3 静态预览</Badge>
            <Badge variant="outline">状态样例</Badge>
          </div>
          <h1 className="mt-4 text-3xl font-semibold tracking-normal">Run 回放与审计预览</h1>
          <p className="mt-3 leading-7 text-muted-foreground">
            这个页面预览历史回放的列表结构：每条 run 会汇总状态、请求摘要、
            关键产物和诊断入口。当前展示静态样例，真实 run 列表与事件回放将在 W5 接入。
          </p>
        </div>
        <Button asChild variant="outline">
          <Link href="/workspace?example=rnaseq-deg">
            <RotateCcw className="h-4 w-4" />
            查看工作台预览
          </Link>
        </Button>
      </div>

      <section className="rounded-md border bg-white p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-2 font-semibold">
            <History className="h-5 w-5 text-primary" />
            Run 状态样例
          </div>
          <Badge variant="outline">非真实运行记录</Badge>
        </div>
        <div className="mt-5 grid gap-3">
          {runStates.map(([state, stateLabel, title, detail]) => {
            const Icon = stateIcon[state as keyof typeof stateIcon];
            return (
              <div key={title} className="grid gap-4 rounded-md border bg-background p-4 md:grid-cols-[auto_1fr_auto] md:items-center">
                <Icon className="h-5 w-5 text-primary" />
                <div>
                  <div className="font-semibold">{title}</div>
                  <div className="mt-1 text-sm text-muted-foreground">{detail}</div>
                </div>
                <Badge variant={state === "failed" ? "destructive" : state === "running" ? "outline" : "secondary"}>
                  {stateLabel}
                </Badge>
              </div>
            );
          })}
        </div>
      </section>

      <section className="mt-6 grid gap-3 md:grid-cols-2">
        <div className="rounded-md border bg-white p-5">
          <div className="font-semibold text-primary">当前已实现</div>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            展示历史页应该如何组织成功、流式更新和失败三类 run 的摘要状态。
          </p>
        </div>
        <div className="rounded-md border bg-white p-5">
          <div className="font-semibold text-primary">后续接入</div>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            从持久化 run repository 读取真实记录，并进入详情页回放 events、artifacts 和 diagnostics。
          </p>
        </div>
      </section>
    </div>
  );
}
