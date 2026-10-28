import { useCallback, useEffect, useState } from "react";
import { getRunBuilds } from "../api/client";
import type { BuildAttempt } from "../api/types";

export interface RunBuildsState {
  attempts: BuildAttempt[];
  error: unknown;
  refresh: () => void;
}

export function useRunBuilds(
  projectId: string,
  runId: string,
  revision: string | undefined,
): RunBuildsState {
  const [attempts, setAttempts] = useState<BuildAttempt[]>([]);
  const [error, setError] = useState<unknown>(null);

  const refresh = useCallback(() => {
    getRunBuilds(projectId, runId).then((builds) => {
      setAttempts(builds.attempts);
      setError(null);
    }, setError);
  }, [projectId, runId]);

  useEffect(() => {
    if (revision !== undefined) {
      refresh();
    }
  }, [refresh, revision]);

  return { attempts, error, refresh };
}
