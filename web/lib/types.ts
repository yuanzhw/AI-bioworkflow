export type TrustStatus =
  | "catalog-approved"
  | "auto-validated"
  | "experimental"
  | "rejected";

export type RecipeInput = {
  type: string;
  description?: string | null;
};

export type RecipeScatter = {
  id: string;
  item: string;
  over: string;
};

export type RecipeStep = {
  id: string;
  role: string;
  optional: boolean;
  scatter?: RecipeScatter | null;
  allowed_tools: string[];
};

export type Recipe = {
  id: string;
  name: string;
  description: string;
  aliases: string[];
  required_inputs: Record<string, RecipeInput>;
  steps: RecipeStep[];
};

export type RecipeListResponse = {
  recipes: Recipe[];
};

export type Runtime = {
  docker?: string | null;
  cpu?: number | null;
  memory?: string | null;
  disks?: string | null;
};

export type Tool = {
  id: string;
  version: string;
  versions: string[];
  aliases: string[];
  description: string;
  runtime: Runtime;
  trust_status: TrustStatus;
};

export type ToolListResponse = {
  tools: Tool[];
};

export type RunStatus = "created" | "running" | "succeeded" | "failed";

export type RunAcceptedResponse = {
  run_id: string;
  status: RunStatus;
  events_url: string;
};
