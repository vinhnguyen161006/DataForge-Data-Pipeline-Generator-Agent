import { useSyncExternalStore } from "react";
import { getAccountEmail } from "./api/session";
import type { CsvReadConfig, RunStatus, SourceFile } from "./api/types";

export interface SavedRun {
  projectId: string;
  runId: string;
  requestText: string;
  createdAt: string;
  status: RunStatus | null;
  updatedAt: string | null;
}

export interface SavedFile {
  source: SourceFile;
  draft: CsvReadConfig;
  confirmed: boolean;
}

export interface UploadDraft {
  projectId: string;
  batchId: string | null;
  files: SavedFile[];
  requirement: string;
  batchComplete: boolean;
  updatedAt: string;
}

interface RunWork {
  runId: string;
  scope: string;
  value: unknown;
  updatedAt: string;
}

interface Progress {
  runs: SavedRun[];
  drafts: UploadDraft[];
  work: RunWork[];
}

const KEY_PREFIX = "dataforge.progress.";
const EMPTY: Progress = { runs: [], drafts: [], work: [] };
const listeners = new Set<() => void>();
let cachedKey: string | null = null;
let cachedRaw: string | null = null;
let cachedValue: Progress = EMPTY;

function storageKey(): string {
  return `${KEY_PREFIX}${getAccountEmail() ?? "anonymous"}`;
}

function read(): Progress {
  const key = storageKey();
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(key);
  } catch {
    raw = null;
  }
  if (key !== cachedKey || raw !== cachedRaw) {
    cachedKey = key;
    cachedRaw = raw;
    try {
      cachedValue = raw ? { ...EMPTY, ...(JSON.parse(raw) as Partial<Progress>) } : EMPTY;
    } catch {
      cachedValue = EMPTY;
    }
  }
  return cachedValue;
}

function write(change: (current: Progress) => Progress): void {
  const next = change(read());
  try {
    localStorage.setItem(storageKey(), JSON.stringify(next));
  } catch {
    return;
  }
  for (const listener of listeners) {
    listener();
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  window.addEventListener("storage", listener);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", listener);
  };
}

function now(): string {
  return new Date().toISOString();
}

export function useProgress(): Progress {
  return useSyncExternalStore(subscribe, read);
}

export function rememberRun(projectId: string, runId: string, requestText: string): void {
  write((current) => ({
    ...current,
    runs: [
      {
        projectId,
        runId,
        requestText,
        createdAt: now(),
        status: null,
        updatedAt: null,
      },
      ...current.runs.filter((run) => run.runId !== runId),
    ],
  }));
}

export function recordRunStatus(
  projectId: string,
  runId: string,
  status: RunStatus,
  updatedAt: string,
): void {
  const known = read().runs.find((run) => run.runId === runId);
  if (known && known.status === status && known.updatedAt === updatedAt) {
    return;
  }
  write((current) => {
    const existing = current.runs.find((run) => run.runId === runId);
    const updated: SavedRun = existing
      ? { ...existing, status, updatedAt }
      : { projectId, runId, requestText: "", createdAt: updatedAt, status, updatedAt };
    return {
      ...current,
      runs: existing
        ? current.runs.map((run) => (run.runId === runId ? updated : run))
        : [updated, ...current.runs],
    };
  });
}

export function forgetRun(runId: string): void {
  write((current) => ({
    ...current,
    runs: current.runs.filter((run) => run.runId !== runId),
    work: current.work.filter((item) => item.runId !== runId),
  }));
}

export function readWork(runId: string, scope: string): RunWork | null {
  return read().work.find((item) => item.runId === runId && item.scope === scope) ?? null;
}

export function saveWork(runId: string, scope: string, value: unknown): void {
  write((current) => ({
    ...current,
    work: [
      { runId, scope, value, updatedAt: now() },
      ...current.work.filter((item) => !(item.runId === runId && item.scope === scope)),
    ],
  }));
}

export function clearWork(runId: string, scope: string): void {
  if (readWork(runId, scope) === null) {
    return;
  }
  write((current) => ({
    ...current,
    work: current.work.filter((item) => !(item.runId === runId && item.scope === scope)),
  }));
}

export function readDraft(projectId: string): UploadDraft | null {
  return read().drafts.find((draft) => draft.projectId === projectId) ?? null;
}

export function saveDraft(draft: Omit<UploadDraft, "updatedAt">): void {
  write((current) => ({
    ...current,
    drafts: [
      { ...draft, updatedAt: now() },
      ...current.drafts.filter((item) => item.projectId !== draft.projectId),
    ],
  }));
}

export function discardDraft(projectId: string): void {
  write((current) => ({
    ...current,
    drafts: current.drafts.filter((draft) => draft.projectId !== projectId),
  }));
}
