import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
} from "react";
import { listProjects } from "../api/client";
import type { Project } from "../api/types";

interface ProjectsState {
  projects: Project[] | null;
  error: unknown;
  reload: () => void;
  add: (project: Project) => void;
}

const ProjectsContext = createContext<ProjectsState | null>(null);

export function ProjectsProvider({ children }: { children: ReactNode }) {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const mounted = useRef(true);

  const load = useCallback(() => {
    listProjects().then(
      (loaded) => {
        if (mounted.current) {
          setProjects(loaded);
          setError(null);
        }
      },
      (caught: unknown) => mounted.current && setError(caught),
    );
  }, []);

  useEffect(() => {
    mounted.current = true;
    load();
    return () => {
      mounted.current = false;
    };
  }, [load]);

  const reload = useCallback(() => {
    setError(null);
    load();
  }, [load]);

  const add = useCallback(
    (project: Project) => setProjects((current) => [...(current ?? []), project]),
    [],
  );

  return (
    <ProjectsContext.Provider value={{ projects, error, reload, add }}>
      {children}
    </ProjectsContext.Provider>
  );
}

export function useProjects(): ProjectsState {
  const state = useContext(ProjectsContext);
  if (state === null) {
    throw new Error("useProjects must be used inside ProjectsProvider");
  }
  return state;
}

export function useProject(projectId: string | undefined): Project | undefined {
  const { projects } = useProjects();
  return projects?.find((project) => project.id === projectId);
}
