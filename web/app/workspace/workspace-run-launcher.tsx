"use client";

import { AlertCircle, CheckCircle2, Loader2, Play } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { createStructuredCompileRun } from "@/lib/api";
import { rnaseqRecipePlan } from "@/lib/examples";
import type { RunAcceptedResponse } from "@/lib/types";

function formatRunError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return "无法创建结构化示例 run。";
}

export function WorkspaceRunLauncher() {
  const [acceptedRun, setAcceptedRun] = useState<RunAcceptedResponse | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleRunExample() {
    setIsSubmitting(true);
    setErrorMessage(null);

    try {
      const accepted = await createStructuredCompileRun(rnaseqRecipePlan, true);
      setAcceptedRun(accepted);
    } catch (error) {
      setAcceptedRun(null);
      setErrorMessage(formatRunError(error));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex w-full flex-col gap-2 sm:w-auto sm:items-end">
      <Button type="button" onClick={handleRunExample} disabled={isSubmitting}>
        {isSubmitting ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Play className="h-4 w-4" />
        )}
        {isSubmitting ? "提交中" : acceptedRun ? "重新运行示例" : "运行示例"}
      </Button>

      {acceptedRun ? (
        <div className="flex max-w-full flex-wrap items-center gap-2 text-xs text-muted-foreground sm:justify-end">
          <Badge variant="secondary">
            <CheckCircle2 className="mr-1 h-3.5 w-3.5" />
            已创建 run
          </Badge>
          <span className="break-all font-mono">{acceptedRun.run_id}</span>
          <span>状态：{acceptedRun.status}</span>
        </div>
      ) : null}

      {errorMessage ? (
        <div className="flex max-w-md items-start gap-2 text-xs leading-5 text-destructive sm:text-right">
          <AlertCircle className="mt-0.5 h-3.5 w-3.5 flex-none" />
          <span>{errorMessage}</span>
        </div>
      ) : null}
    </div>
  );
}
