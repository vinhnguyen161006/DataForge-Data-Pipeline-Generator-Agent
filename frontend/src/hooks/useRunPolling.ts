import { useCallback, useEffect, useState } from "react";
import { getRun } from "../api/client";
import type { Run, RunStatus } from "../api/types";

const SETTLED: ReadonlySet<RunStatus> = new Set<RunStatus>([
  "waiting_clarification",
  "waiting_design_approval",
  "waiting_code_approval",
  "published",
  "failed",
]);

function isSettled(status: RunStatus): boolean {
  return SETTLED.has(status);
}

export interface RunPollingState {
  run: Run | null;
  error: unknown;
  setRun: (run: Run) => void;
  refresh: () => void;
}

export function useRunPolling(
  projectId: string,
  runId: string,
  intervalMs = 2000,
): RunPollingState {
  const [run, setRun] = useState<Run | null>(null);
  const [error, setError] = useState<unknown>(null);
  const settled = run !== null && isSettled(run.status);

  useEffect(() => {
    if (settled) {
      return;
    }
    let active = true;
    let timer: number | undefined;

    const poll = async () => {
      try {
        const next = await getRun(projectId, runId);
        if (!active) {
          return;
        }
        setRun(next);
        setError(null);
        if (isSettled(next.status)) {
          return;
        }
      } catch (caught) {
        if (!active) {
          return;
        }
        setError(caught);
      }
      timer = window.setTimeout(poll, intervalMs);
    };

    poll();
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [projectId, runId, intervalMs, settled]);

  const refresh = useCallback(() => {
    getRun(projectId, runId).then(setRun, setError);
  }, [projectId, runId]);

  return { run, error, setRun, refresh };
}
