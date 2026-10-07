export type ProjectRole = "engineer" | "reviewer";
export type ReviewMode = "team" | "solo";
export type BatchStatus = "uploading" | "ready";

export type RunStatus =
  | "running"
  | "waiting_clarification"
  | "waiting_design_approval"
  | "waiting_job"
  | "waiting_code_approval"
  | "published"
  | "failed";

export interface RegisterRequest {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
}

export interface ProjectCreate {
  name: string;
  slug: string;
  review_mode?: ReviewMode;
}

export interface Project {
  id: string;
  name: string;
  slug: string;
  review_mode: ReviewMode;
  roles: ProjectRole[];
}

export interface MemberAdd {
  email: string;
  role: ProjectRole;
}

export interface CsvReadConfig {
  encoding: string;
  delimiter: string;
  quote: string;
  escape: string;
  has_header: boolean;
  skip_rows: number;
  null_tokens: string[];
  date_format: string | null;
  timestamp_format: string | null;
}

export interface SourceFile {
  id: string;
  filename: string;
  sha256: string;
  size_bytes: number;
  read_config: CsvReadConfig;
  read_config_confirmed: boolean;
  columns: string[];
  preview: (string | null)[][];
  warnings: string[];
}

export interface Batch {
  id: string;
  status: BatchStatus;
  files: SourceFile[];
}

export interface RunCreate {
  batch_id: string;
  request_text: string;
}

export interface Run {
  id: string;
  status: RunStatus;
  current_step: string | null;
  pending: Record<string, unknown> | null;
  error: string | null;
  updated_at: string;
}

export interface ClarificationAnswer {
  question: string;
  answer: string;
}

export interface FactTable {
  rationale: string;
  name: string;
  grain: string;
  source_tables: string[];
  measures: string[];
  dimension_keys: string[];
}

export interface DimensionTable {
  rationale: string;
  name: string;
  business_key: string[];
  source_table: string;
  attributes: string[];
}

export interface KeyDefinition {
  rationale: string;
  table: string;
  columns: string[];
  kind: "primary" | "business" | "composite";
}

export interface RelationshipDefinition {
  rationale: string;
  child_table: string;
  child_columns: string[];
  parent_table: string;
  parent_columns: string[];
  cardinality: "many_to_one" | "one_to_one";
}

export interface MetricDefinition {
  rationale: string;
  name: string;
  definition: string;
  expression: string;
  fact_table: string;
}

export interface CleaningRule {
  rationale: string;
  table: string;
  columns: string[];
  condition: string;
  action: "quarantine" | "fail_pipeline" | "set_default" | "deduplicate";
  default_value: string | null;
}

export interface UpdatePolicy {
  rationale: string;
  mode: "snapshot_replace";
  required_files: string[];
}

export interface CardSpec {
  key: string;
  title: string;
  type: "kpi" | "line" | "bar";
  metric: string;
  dimension: string | null;
}

export interface DashboardRequirements {
  rationale: string;
  metrics: string[];
  dimensions: string[];
  filters: string[];
  cards: CardSpec[];
}

export interface Constraint {
  layer: "silver" | "mart";
  model: string;
  columns: string[];
  kind: "not_null" | "unique" | "accepted_values" | "relationship" | "expression";
  params: Record<string, string | string[]>;
  evidence: string | null;
}

export interface DataDesign {
  facts: FactTable[];
  dimensions: DimensionTable[];
  keys: KeyDefinition[];
  relationships: RelationshipDefinition[];
  metrics: MetricDefinition[];
  cleaning_rules: CleaningRule[];
  update_policy: UpdatePolicy;
  dashboard: DashboardRequirements;
  constraints: Constraint[];
  assumptions: string[];
}

export interface DesignDecision {
  decision: "approve" | "return";
  edited_design?: DataDesign | null;
  comment?: string | null;
}

export interface CodeDecision {
  decision: "approve" | "return";
  fingerprint: string;
  comment?: string | null;
}

export interface FileEdit {
  path: string;
  content: string;
}

export interface PullRequestCreate {
  owner: string;
  repo: string;
  base_branch?: string;
}
