export type TrustStatus =
  | "catalog-approved"
  | "auto-validated"
  | "experimental"
  | "rejected";

export type ExecutionVerificationStatus =
  | "unverified"
  | "smoke-tested"
  | "e2e-validated";

export type ExecutionVerification = {
  status: ExecutionVerificationStatus;
  evidence: string[];
};

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
  execution_verification: ExecutionVerification;
};

export type ToolListResponse = {
  tools: Tool[];
};

export type JsonPrimitive = string | number | boolean | null;

export type JsonValue = JsonPrimitive | JsonObject | JsonValue[];

export type JsonObject = {
  [key: string]: JsonValue;
};

export type RunStatus = "created" | "running" | "succeeded" | "failed";

export type CompileWorkflowRequest = {
  payload: JsonObject;
  check?: boolean;
};

export type NaturalLanguageRunRequest = {
  request: string;
  planner_model?: string | null;
  check?: boolean;
};

export type RunAcceptedResponse = {
  run_id: string;
  status: RunStatus;
  events_url: string;
};

export type WorkflowArtifactSummary = {
  name: string;
  content_type: string;
  updated_at: string;
};

export type RunDiagnosticSummary = {
  analysis_error_count: number;
  analysis_warning_count: number;
  repair_action_count: number;
  check_performed: boolean;
  is_valid: boolean;
};

export type RunSummary = {
  run_id: string;
  status: RunStatus;
  kind: string;
  request_summary: string | null;
  events_url: string;
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  diagnostic_summary: RunDiagnosticSummary;
};

export type RunListResponse = {
  runs: RunSummary[];
  limit: number;
  offset: number;
  total: number;
};

export type CatalogRetrievalRecipe = {
  id: string;
  score: number;
  matched_terms: string[];
  matched_fields: string[];
  reason: string;
};

export type CatalogRetrievalTool = {
  id: string;
  version: string;
  score: number;
  matched_terms: string[];
  matched_fields: string[];
  trust_status: TrustStatus;
  execution_verification?: ExecutionVerification;
  reason: string;
};

export type CatalogRetrievalArtifact = {
  query: string;
  strategy: string;
  recipes: CatalogRetrievalRecipe[];
  tools: CatalogRetrievalTool[];
  fallback_used: boolean;
  fallback_reason: string | null;
};

export type WorkflowArtifacts = {
  catalog_retrieval: CatalogRetrievalArtifact | null;
  plan: JsonObject | null;
  workflow_ir: JsonObject;
  wdl: string;
  extras: Record<string, JsonValue>;
  manifest: WorkflowArtifactSummary[];
};

export type DiagnosticReport = {
  analysis_errors: string[];
  analysis_warnings: string[];
  repair_actions: string[];
  validation_message: string;
  is_valid: boolean;
  succeeded: boolean;
  check_performed: boolean;
  reviewer_attempt_count: number;
  reviewer_repair_status: string | null;
  reviewer_rejection_reason: string | null;
  reviewer_diagnostics: string[];
  reviewer_patch_applied: boolean;
};

export type WorkflowRunSnapshotResponse = {
  run_id: string;
  status: RunStatus;
  kind: string | null;
  request: string | JsonObject | null;
  events_url: string | null;
  created_at: string | null;
  updated_at: string | null;
  completed_at: string | null;
  artifacts: WorkflowArtifacts;
  diagnostics: DiagnosticReport;
};

export type RunEventType =
  | "run.created"
  | "node.started"
  | "node.completed"
  | "node.failed"
  | "artifact.updated"
  | "repair.proposed"
  | "repair.rejected"
  | "repair.applied"
  | "validation.completed"
  | "run.completed";

export type RunEvent = {
  event_id: string;
  run_id: string;
  sequence: number;
  type: RunEventType;
  timestamp: string;
  summary: string;
  node: string | null;
  payload: JsonObject;
};
