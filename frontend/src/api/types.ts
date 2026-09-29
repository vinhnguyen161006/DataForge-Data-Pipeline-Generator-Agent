export type ProjectRole = "engineer" | "reviewer";
export type ReviewMode = "team" | "solo";

export type RunStatus =
  | "running"
  | "waiting_clarification"
  | "waiting_design_approval"
  | "waiting_job"
  | "waiting_code_approval"
  | "published"
  | "failed";

export interface Project {
  id: string;
  name: string;
  slug: string;
  review_mode: ReviewMode;
  roles: ProjectRole[];
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
  status: "uploading" | "ready";
  files: SourceFile[];
}

export interface Run {
  id: string;
  status: RunStatus;
  current_step: string | null;
  pending: Record<string, unknown> | null;
  error: string | null;
  updated_at: string;
}

export interface DesignDecision {
  decision: "approve" | "return";
  edited_design?: Record<string, unknown>;
  comment?: string;
}

export interface CodeDecision {
  decision: "approve" | "return";
  fingerprint: string;
  comment?: string;
}

export interface FileEdit {
  path: string;
  content: string;
}
