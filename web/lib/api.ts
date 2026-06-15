import type {
  CompileWorkflowRequest,
  JsonObject,
  NaturalLanguageRunRequest,
  RecipeListResponse,
  RunAcceptedResponse,
  ToolListResponse,
  WorkflowRunSnapshotResponse,
} from "@/lib/types";

const defaultApiBaseUrl = "http://127.0.0.1:8010";

export const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? defaultApiBaseUrl;

export const apiDocsUrl = `${apiBaseUrl}/docs`;

type JsonRequestInit = RequestInit & {
  next?: {
    revalidate?: number;
  };
};

async function requestJson<T>(path: string, init: JsonRequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers,
  });

  if (!response.ok) {
    const detail = await response.text();
    const suffix = detail ? `: ${detail}` : "";
    throw new Error(`API request failed: ${response.status} ${response.statusText}${suffix}`);
  }

  return response.json() as Promise<T>;
}

async function getJson<T>(path: string): Promise<T> {
  return requestJson<T>(path, {
    next: {
      revalidate: 30,
    },
  });
}

async function postJson<T>(path: string, body: JsonObject): Promise<T> {
  return requestJson<T>(path, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function listRecipes(): Promise<RecipeListResponse> {
  return getJson<RecipeListResponse>("/api/recipes");
}

export function listTools(): Promise<ToolListResponse> {
  return getJson<ToolListResponse>("/api/tools");
}

export function createNaturalLanguageRun(
  request: string,
  check = true,
  plannerModel?: string | null,
): Promise<RunAcceptedResponse> {
  const body: NaturalLanguageRunRequest = {
    request,
    check,
  };

  if (plannerModel) {
    body.planner_model = plannerModel;
  }

  return postJson<RunAcceptedResponse>("/api/runs", body);
}

export function createStructuredCompileRun(
  payload: JsonObject,
  check = true,
): Promise<RunAcceptedResponse> {
  const body: CompileWorkflowRequest = {
    payload,
    check,
  };

  return postJson<RunAcceptedResponse>("/api/compile", body);
}

export function getRunSnapshot(runId: string): Promise<WorkflowRunSnapshotResponse> {
  return requestJson<WorkflowRunSnapshotResponse>(`/api/runs/${encodeURIComponent(runId)}`, {
    cache: "no-store",
  });
}

export function buildRunEventsUrl(eventsUrl: string, afterSequence?: number): string {
  const url = new URL(eventsUrl, apiBaseUrl);

  if (afterSequence !== undefined && afterSequence > 0) {
    url.searchParams.set("after", String(afterSequence));
  }

  return url.toString();
}
