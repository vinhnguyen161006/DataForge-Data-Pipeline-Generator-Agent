import { useCallback, useEffect, useState } from "react";
import { clearWork, readWork, saveWork } from "../progress";

export interface RunWorkState<T> {
  value: T;
  setValue: (value: T | ((current: T) => T)) => void;
  restoredAt: string | null;
  clear: () => void;
}

export function useRunWork<T>(
  runId: string,
  scope: string,
  fallback: () => T,
  accept: (value: unknown) => value is T,
  isEmpty: (value: T) => boolean,
): RunWorkState<T> {
  const [restored] = useState(() => {
    const saved = readWork(runId, scope);
    return saved && accept(saved.value) ? { value: saved.value, at: saved.updatedAt } : null;
  });
  const [value, setValue] = useState<T>(() => restored?.value ?? fallback());

  useEffect(() => {
    if (isEmpty(value)) {
      clearWork(runId, scope);
    } else {
      saveWork(runId, scope, value);
    }
  }, [runId, scope, value, isEmpty]);

  const clear = useCallback(() => clearWork(runId, scope), [runId, scope]);

  return { value, setValue, restoredAt: restored?.at ?? null, clear };
}

export function formatSavedAt(iso: string): string {
  return new Date(iso).toLocaleString([], {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}
