import { useRef, useState } from "react";
import { confirmReadConfig, createBatch, uploadFile } from "../api/client";
import type { CsvReadConfig, SourceFile } from "../api/types";
import type { SavedFile, UploadDraft } from "../progress";

export type FileStatus = "uploading" | "review" | "confirming" | "confirmed" | "failed";

export interface FileEntry {
  key: string;
  name: string;
  size: number;
  file: File | null;
  status: FileStatus;
  source: SourceFile | null;
  draft: CsvReadConfig | null;
  error: unknown;
}

export interface BatchUpload {
  entries: FileEntry[];
  selected: FileEntry | null;
  knownBatchId: string | null;
  select: (key: string) => void;
  addFiles: (files: File[]) => Promise<void>;
  retry: (key: string) => Promise<void>;
  remove: (key: string) => void;
  editDraft: (key: string, draft: CsvReadConfig) => void;
  confirm: (key: string) => Promise<void>;
  batchId: () => Promise<string>;
}

export function savedFilesOf(entries: FileEntry[]): SavedFile[] {
  return entries.flatMap((entry) =>
    entry.source && entry.draft
      ? [{ source: entry.source, draft: entry.draft, confirmed: entry.status === "confirmed" }]
      : [],
  );
}

function statusOf(source: SourceFile): FileStatus {
  return source.read_config_confirmed ? "confirmed" : "review";
}

function restored(saved: SavedFile): FileEntry {
  return {
    key: saved.source.id,
    name: saved.source.filename,
    size: saved.source.size_bytes,
    file: null,
    status: saved.confirmed ? "confirmed" : "review",
    source: saved.source,
    draft: saved.draft,
    error: null,
  };
}

export function useBatchUpload(projectId: string, initial: UploadDraft | null): BatchUpload {
  const [entries, setEntries] = useState<FileEntry[]>(() => initial?.files.map(restored) ?? []);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [knownBatchId, setKnownBatchId] = useState<string | null>(initial?.batchId ?? null);
  const declaredFiles = useRef<string[]>(initial?.files.map((file) => file.source.filename) ?? []);
  const batch = useRef<Promise<string> | null>(
    initial?.batchId ? Promise.resolve(initial.batchId) : null,
  );

  const patch = (key: string, change: Partial<FileEntry>) =>
    setEntries((current) =>
      current.map((entry) => (entry.key === key ? { ...entry, ...change } : entry)),
    );

  const batchId = (): Promise<string> => {
    batch.current ??= createBatch(projectId, declaredFiles.current).then(
      (created) => {
        setKnownBatchId(created.id);
        return created.id;
      },
      (caught: unknown) => {
        batch.current = null;
        throw caught;
      },
    );
    return batch.current;
  };

  const send = async (key: string, file: File) => {
    patch(key, { status: "uploading", error: null });
    try {
      const source = await uploadFile(projectId, await batchId(), file);
      patch(key, { source, draft: source.read_config, status: statusOf(source) });
    } catch (caught) {
      patch(key, { status: "failed", error: caught });
    }
  };

  const addFiles = async (files: File[]) => {
    if (batch.current === null) {
      declaredFiles.current = [
        ...new Set([...declaredFiles.current, ...files.map((file) => file.name)]),
      ];
    }
    const added: FileEntry[] = files.map((file) => ({
      key: crypto.randomUUID(),
      name: file.name,
      size: file.size,
      file,
      status: "uploading",
      source: null,
      draft: null,
      error: null,
    }));
    setEntries((current) => [...current, ...added]);
    setSelectedKey((current) => current ?? added[0]?.key ?? null);
    for (const entry of added) {
      if (entry.file) {
        await send(entry.key, entry.file);
      }
    }
  };

  const find = (key: string) => entries.find((entry) => entry.key === key);

  const retry = async (key: string) => {
    const entry = find(key);
    if (entry?.file) {
      await send(key, entry.file);
    }
  };

  const remove = (key: string) => {
    if (batch.current !== null) {
      return;
    }
    const entry = find(key);
    if (entry) {
      declaredFiles.current = declaredFiles.current.filter((name) => name !== entry.name);
    }
    setEntries((current) => current.filter((entry) => entry.key !== key));
    setSelectedKey((current) => (current === key ? null : current));
  };

  const editDraft = (key: string, draft: CsvReadConfig) =>
    patch(key, { draft, status: "review", error: null });

  const confirm = async (key: string) => {
    const entry = find(key);
    if (!entry?.source || !entry.draft) {
      return;
    }
    patch(key, { status: "confirming", error: null });
    try {
      const source = await confirmReadConfig(
        projectId,
        await batchId(),
        entry.source.id,
        entry.draft,
      );
      patch(key, { source, draft: source.read_config, status: statusOf(source) });
    } catch (caught) {
      patch(key, { status: "review", error: caught });
    }
  };

  const selected =
    entries.find((entry) => entry.key === selectedKey) ??
    entries.find((entry) => entry.source !== null) ??
    null;

  return {
    entries,
    selected,
    knownBatchId,
    select: setSelectedKey,
    addFiles,
    retry,
    remove,
    editDraft,
    confirm,
    batchId,
  };
}
