import type {
  Batch,
  CodeDecision,
  CsvReadConfig,
  DesignDecision,
  FileEdit,
  Project,
  Run,
  SourceFile,
} from "./types";

export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "/api";

function todo(name: string): never {
  throw new Error(`TODO: implement ${name}`);
}

export async function login(email: string, password: string): Promise<string> {
  return todo("login: POST /auth/token and store the bearer token");
}

export async function listProjects(): Promise<Project[]> {
  return todo("listProjects: GET /projects");
}

export async function createBatch(projectId: string): Promise<Batch> {
  return todo("createBatch: POST /projects/{id}/batches");
}

export async function uploadFile(
  projectId: string,
  batchId: string,
  file: File,
): Promise<SourceFile> {
  return todo("uploadFile: multipart POST /projects/{id}/batches/{batchId}/files");
}

export async function confirmReadConfig(
  projectId: string,
  batchId: string,
  fileId: string,
  config: CsvReadConfig,
): Promise<SourceFile> {
  return todo("confirmReadConfig: PUT .../files/{fileId}/read-config");
}

export async function markBatchReady(projectId: string, batchId: string): Promise<Batch> {
  return todo("markBatchReady: POST .../batches/{batchId}/ready");
}

export async function createRun(
  projectId: string,
  batchId: string,
  requestText: string,
): Promise<Run> {
  return todo("createRun: POST /projects/{id}/runs");
}

export async function getRun(projectId: string, runId: string): Promise<Run> {
  return todo("getRun: GET /projects/{id}/runs/{runId}");
}

export async function answerClarifications(
  projectId: string,
  runId: string,
  answers: { question: string; answer: string }[],
): Promise<Run> {
  return todo("answerClarifications: POST .../runs/{runId}/clarifications");
}

export async function decideDesign(
  projectId: string,
  runId: string,
  body: DesignDecision,
): Promise<Run> {
  return todo("decideDesign: POST .../runs/{runId}/design-decision");
}

export async function getCode(projectId: string, runId: string): Promise<Record<string, unknown>> {
  return todo("getCode: GET .../runs/{runId}/code");
}

export async function editCode(projectId: string, runId: string, edits: FileEdit[]): Promise<Run> {
  return todo("editCode: PUT .../runs/{runId}/code");
}

export async function getEvidence(
  projectId: string,
  runId: string,
): Promise<Record<string, unknown>> {
  return todo("getEvidence: GET .../runs/{runId}/evidence");
}

export async function decideCode(
  projectId: string,
  runId: string,
  body: CodeDecision,
): Promise<Run> {
  return todo("decideCode: POST .../runs/{runId}/code-decision");
}

export async function downloadZip(projectId: string, runId: string): Promise<Blob> {
  return todo("downloadZip: GET .../export/zip");
}

export async function openPullRequest(
  projectId: string,
  runId: string,
  target: { owner: string; repo: string; base_branch?: string },
): Promise<{ url: string }> {
  return todo("openPullRequest: POST .../export/pull-request");
}
