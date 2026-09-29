import type { Run } from "../api/types";

export interface RunPollingState {
  run: Run | null;
  error: string | null;
}

export function useRunPolling(
  projectId: string,
  runId: string,
  intervalMs = 2000,
): RunPollingState {
  throw new Error(
    "TODO: poll getRun every intervalMs until a waiting/terminal status; stop on unmount",
  );
}
