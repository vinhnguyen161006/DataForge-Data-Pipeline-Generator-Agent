import { clearToken, getToken, setToken } from "./session";
import type {
  Batch,
  ClarificationAnswer,
  CodeDecision,
  CsvReadConfig,
  DesignDecision,
  FileEdit,
  MemberAdd,
  Project,
  ProjectCreate,
  PullRequestCreate,
  Run,
  SourceFile,
  TokenResponse,
} from "./types";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";

const HTTP_UNAUTHORIZED = 401;

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

interface ValidationIssue {
  loc: (string | number)[];
  msg: string;
}

function describeDetail(detail: unknown): string | null {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    return (detail as ValidationIssue[])
      .map((issue) => `${issue.loc.slice(1).join(".")}: ${issue.msg}`)
      .join("; ");
  }
  return null;
}

async function errorMessage(response: Response): Promise<string> {
  const fallback = `${response.status} ${response.statusText}`.trim();
  try {
    const body: unknown = await response.json();
    const detail = describeDetail((body as { detail?: unknown }).detail);
    return detail ?? fallback;
  } catch {
    return fallback;
  }
}

async function send(path: string, init: RequestInit = {}): Promise<Response> {
  const headers = new Headers(init.headers);
  const token = getToken();
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  if (response.status === HTTP_UNAUTHORIZED) {
    clearToken();
  }
  if (!response.ok) {
    throw new ApiError(response.status, await errorMessage(response));
  }
  return response;
}

async function requestJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await send(path, init);
  return (await response.json()) as T;
}

async function requestEmpty(path: string, init: RequestInit = {}): Promise<void> {
  await send(path, init);
}

function jsonBody(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

function projectPath(projectId: string): string {
  return `/projects/${encodeURIComponent(projectId)}`;
}

function batchPath(projectId: string, batchId: string): string {
  return `${projectPath(projectId)}/batches/${encodeURIComponent(batchId)}`;
}

function runPath(projectId: string, runId: string): string {
  return `${projectPath(projectId)}/runs/${encodeURIComponent(runId)}`;
}

export async function register(email: string, password: string): Promise<void> {
  const token = await requestJson<TokenResponse>(
    "/auth/register",
    jsonBody("POST", { email, password }),
  );
  setToken(token.access_token);
}

export async function login(email: string, password: string): Promise<void> {
  const form = new URLSearchParams({ username: email, password });
  const token = await requestJson<TokenResponse>("/auth/token", { method: "POST", body: form });
  setToken(token.access_token);
}

export function logout(): void {
  clearToken();
}

export function listProjects(): Promise<Project[]> {
  return requestJson<Project[]>("/projects");
}

export function createProject(body: ProjectCreate): Promise<Project> {
  return requestJson<Project>("/projects", jsonBody("POST", body));
}

export function addMember(projectId: string, body: MemberAdd): Promise<void> {
  return requestEmpty(`${projectPath(projectId)}/members`, jsonBody("POST", body));
}

export function getApprovalHistory(projectId: string): Promise<Record<string, unknown>[]> {
  return requestJson<Record<string, unknown>[]>(`${projectPath(projectId)}/approvals`);
}

export function createBatch(projectId: string): Promise<Batch> {
  return requestJson<Batch>(`${projectPath(projectId)}/batches`, { method: "POST" });
}

export function uploadFile(projectId: string, batchId: string, file: File): Promise<SourceFile> {
  const form = new FormData();
  form.append("file", file);
  return requestJson<SourceFile>(`${batchPath(projectId, batchId)}/files`, {
    method: "POST",
    body: form,
  });
}

export function confirmReadConfig(
  projectId: string,
  batchId: string,
  fileId: string,
  config: CsvReadConfig,
): Promise<SourceFile> {
  return requestJson<SourceFile>(
    `${batchPath(projectId, batchId)}/files/${encodeURIComponent(fileId)}/read-config`,
    jsonBody("PUT", { read_config: config }),
  );
}

export function markBatchReady(projectId: string, batchId: string): Promise<Batch> {
  return requestJson<Batch>(`${batchPath(projectId, batchId)}/ready`, { method: "POST" });
}

export function createRun(projectId: string, batchId: string, requestText: string): Promise<Run> {
  return requestJson<Run>(
    `${projectPath(projectId)}/runs`,
    jsonBody("POST", { batch_id: batchId, request_text: requestText }),
  );
}

export function getRun(projectId: string, runId: string): Promise<Run> {
  return requestJson<Run>(runPath(projectId, runId));
}

export function answerClarifications(
  projectId: string,
  runId: string,
  answers: ClarificationAnswer[],
): Promise<Run> {
  return requestJson<Run>(
    `${runPath(projectId, runId)}/clarifications`,
    jsonBody("POST", { answers }),
  );
}

export function decideDesign(projectId: string, runId: string, body: DesignDecision): Promise<Run> {
  return requestJson<Run>(`${runPath(projectId, runId)}/design-decision`, jsonBody("POST", body));
}

export function getCode(projectId: string, runId: string): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>(`${runPath(projectId, runId)}/code`);
}

export function editCode(projectId: string, runId: string, edits: FileEdit[]): Promise<Run> {
  return requestJson<Run>(`${runPath(projectId, runId)}/code`, jsonBody("PUT", edits));
}

export function getEvidence(projectId: string, runId: string): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>(`${runPath(projectId, runId)}/evidence`);
}

export function decideCode(projectId: string, runId: string, body: CodeDecision): Promise<Run> {
  return requestJson<Run>(`${runPath(projectId, runId)}/code-decision`, jsonBody("POST", body));
}

export function retryDashboard(projectId: string, runId: string): Promise<Run> {
  return requestJson<Run>(`${runPath(projectId, runId)}/dashboard/retry`, { method: "POST" });
}

export async function downloadZip(projectId: string, runId: string): Promise<Blob> {
  const response = await send(`${runPath(projectId, runId)}/export/zip`);
  return response.blob();
}

export function openPullRequest(
  projectId: string,
  runId: string,
  target: PullRequestCreate,
): Promise<{ url: string }> {
  return requestJson<{ url: string }>(
    `${runPath(projectId, runId)}/export/pull-request`,
    jsonBody("POST", target),
  );
}
