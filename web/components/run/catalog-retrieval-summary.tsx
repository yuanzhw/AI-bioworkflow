"use client";

import {
  AlertTriangle,
  BadgeCheck,
  Database,
  FlaskConical,
  Search,
  ShieldCheck,
  Tags,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  formatRetrievalScore,
  getTopCatalogRecipe,
  getTopCatalogTools,
  hasCatalogRetrieval,
  summarizeMatchedTerms,
} from "@/lib/catalog-retrieval";
import type {
  CatalogRetrievalArtifact,
  CatalogRetrievalRecipe,
  CatalogRetrievalTool,
  ExecutionVerification,
} from "@/lib/types";
import { cn } from "@/lib/utils";

type CatalogRetrievalSummaryProps = {
  className?: string;
  compact?: boolean;
  emptyMessage?: string;
  retrieval: CatalogRetrievalArtifact | null;
  title?: string;
};

function MatchedTerms({ terms }: { terms: string[] }) {
  const { hiddenCount, visibleTerms } = summarizeMatchedTerms(terms);

  if (!visibleTerms.length) {
    return <span className="text-xs text-muted-foreground">无命中词</span>;
  }

  return (
    <div className="flex flex-wrap gap-1.5">
      {visibleTerms.map((term) => (
        <Badge key={term} variant="outline">
          {term}
        </Badge>
      ))}
      {hiddenCount ? <Badge variant="outline">+{hiddenCount}</Badge> : null}
    </div>
  );
}

function ExecutionVerificationBadge({
  verification,
}: {
  verification?: ExecutionVerification;
}) {
  if (!verification) {
    return (
      <Badge variant="outline" className="gap-1.5" title="历史 artifact 未记录执行验证状态">
        <AlertTriangle className="h-3.5 w-3.5" />
        执行状态未记录
      </Badge>
    );
  }

  if (verification.status === "unverified") {
    return (
      <Badge variant="outline" className="gap-1.5" title="工具尚无成功执行验证记录">
        <AlertTriangle className="h-3.5 w-3.5" />
        执行未验证
      </Badge>
    );
  }

  if (verification.status === "smoke-tested") {
    return (
      <Badge variant="secondary" className="gap-1.5" title="工具已通过 smoke test">
        <FlaskConical className="h-3.5 w-3.5" />
        Smoke test 已验证
      </Badge>
    );
  }

  return (
    <Badge variant="secondary" className="gap-1.5" title="工具已通过小数据端到端执行">
      <BadgeCheck className="h-3.5 w-3.5" />
      E2E 已验证
    </Badge>
  );
}

function CandidateMeta({
  candidate,
}: {
  candidate: CatalogRetrievalRecipe | CatalogRetrievalTool;
}) {
  const isTool = "version" in candidate;
  const version = isTool ? candidate.version : null;
  const trustStatus = isTool ? candidate.trust_status : null;
  const verification = isTool ? candidate.execution_verification : undefined;

  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="font-semibold">{candidate.id}</span>
      {version ? <Badge variant="outline">v{version}</Badge> : null}
      {trustStatus ? (
        <Badge variant="secondary" className="gap-1.5">
          <ShieldCheck className="h-3.5 w-3.5" />
          {trustStatus}
        </Badge>
      ) : null}
      {isTool ? <ExecutionVerificationBadge verification={verification} /> : null}
      <Badge variant="outline">score {formatRetrievalScore(candidate.score)}</Badge>
    </div>
  );
}

function CandidateRow({
  candidate,
  compact,
  kind,
}: {
  candidate: CatalogRetrievalRecipe | CatalogRetrievalTool;
  compact: boolean;
  kind: "recipe" | "tool";
}) {
  return (
    <div className="rounded-md border bg-background p-3">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 rounded-md border bg-white p-2">
          {kind === "recipe" ? (
            <Database className="h-4 w-4 text-primary" />
          ) : (
            <ShieldCheck className="h-4 w-4 text-primary" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <CandidateMeta candidate={candidate} />
          {!compact ? (
            <p className="mt-2 break-words text-sm leading-6 text-muted-foreground">
              {candidate.reason}
            </p>
          ) : null}
          <div className="mt-3">
            <MatchedTerms terms={candidate.matched_terms} />
          </div>
          {!compact && candidate.matched_fields.length ? (
            <div className="mt-3 flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
              <Tags className="h-3.5 w-3.5" />
              {candidate.matched_fields.map((field) => (
                <span key={field}>{field}</span>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function CatalogRetrievalSummary({
  className,
  compact = false,
  emptyMessage = "当前 run 尚未记录 Catalog Retrieval；结构化编译入口不会触发该阶段。",
  retrieval,
  title = "Catalog Retrieval",
}: CatalogRetrievalSummaryProps) {
  if (!hasCatalogRetrieval(retrieval)) {
    return (
      <section className={cn("rounded-md border bg-background p-4", className)}>
        <div className="flex items-center gap-2 font-semibold">
          <Search className="h-4 w-4 text-primary" />
          {title}
        </div>
        <p className="mt-2 text-sm leading-6 text-muted-foreground">{emptyMessage}</p>
      </section>
    );
  }

  const topRecipe = getTopCatalogRecipe(retrieval);
  const topTools = getTopCatalogTools(retrieval, compact ? 4 : 8);

  return (
    <section className={cn("rounded-md border bg-white p-4", className)}>
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <Search className="h-5 w-5 text-primary" />
            <h3 className="font-semibold">{title}</h3>
            <Badge variant="outline">{retrieval.strategy}</Badge>
            <Badge variant="secondary">approved catalog only</Badge>
          </div>
          <p className="mt-2 break-words text-sm leading-6 text-muted-foreground">
            {retrieval.query}
          </p>
        </div>
        {retrieval.fallback_used ? (
          <Badge variant="outline" className="gap-1.5">
            <AlertTriangle className="h-3.5 w-3.5" />
            fallback
          </Badge>
        ) : (
          <Badge variant="outline" className="gap-1.5">
            <ShieldCheck className="h-3.5 w-3.5" />
            direct match
          </Badge>
        )}
      </div>

      {retrieval.fallback_used && retrieval.fallback_reason ? (
        <div className="mt-4 rounded-md border bg-background p-3 text-sm leading-6 text-muted-foreground">
          {retrieval.fallback_reason}
        </div>
      ) : null}

      <div className={cn("mt-4 grid gap-4", compact ? "lg:grid-cols-2" : "xl:grid-cols-[0.85fr_1.15fr]")}>
        <div>
          <div className="mb-2 text-sm font-semibold">Top recipe</div>
          {topRecipe ? (
            <CandidateRow candidate={topRecipe} compact={compact} kind="recipe" />
          ) : (
            <div className="rounded-md border bg-background p-3 text-sm text-muted-foreground">
              暂无 recipe 候选。
            </div>
          )}
        </div>

        <div>
          <div className="mb-2 text-sm font-semibold">Top tools</div>
          {topTools.length ? (
            <div className="grid gap-2">
              {topTools.map((tool) => (
                <CandidateRow
                  key={`${tool.id}:${tool.version}`}
                  candidate={tool}
                  compact={compact}
                  kind="tool"
                />
              ))}
            </div>
          ) : (
            <div className="rounded-md border bg-background p-3 text-sm text-muted-foreground">
              暂无 tool 候选。
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
