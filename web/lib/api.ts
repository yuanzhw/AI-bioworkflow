import type { RecipeListResponse, ToolListResponse } from "@/lib/types";

const defaultApiBaseUrl = "http://127.0.0.1:8010";

export const apiBaseUrl =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ?? defaultApiBaseUrl;

export const apiDocsUrl = `${apiBaseUrl}/docs`;

async function requestJson<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    headers: {
      Accept: "application/json",
    },
    next: {
      revalidate: 30,
    },
  });

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status} ${response.statusText}`);
  }

  return response.json() as Promise<T>;
}

export function listRecipes(): Promise<RecipeListResponse> {
  return requestJson<RecipeListResponse>("/api/recipes");
}

export function listTools(): Promise<ToolListResponse> {
  return requestJson<ToolListResponse>("/api/tools");
}
