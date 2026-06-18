import { GitBranch } from "lucide-react";

export function GraphEmptyState() {
  return (
    <div className="rounded-md border bg-background p-5">
      <div className="flex items-center gap-2 font-semibold">
        <GitBranch className="h-5 w-5 text-primary" />
        DAG 尚不可用
      </div>
      <p className="mt-2 text-sm leading-6 text-muted-foreground">
        当前 run 尚未保存可展示的 Workflow IR。
      </p>
    </div>
  );
}
