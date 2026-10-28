import "../upload.css";
import "../run.css";
import { useEffect } from "react";
import type { Run } from "../api/types";
import { BuildLog } from "../components/run/BuildLog";
import { ClarificationPanel } from "../components/run/ClarificationPanel";
import { WorkflowSteps } from "../components/run/WorkflowSteps";
import { LoadError } from "../components/workspace/LoadError";
import { useProject } from "../hooks/useProjects";
import { useRunBuilds } from "../hooks/useRunBuilds";
import { useRunPolling } from "../hooks/useRunPolling";
import { recordRunStatus } from "../progress";
import { navigate } from "../router";
import { DesignGatePage } from "./DesignGatePage";

const SHORT_ID_LENGTH = 8;

const WORKING: Record<string, { title: string; text: string }> = {
  profile: {
    title: "Data profiling",
    text: "Statistics are computed in DuckDB inside the sandbox. The Modeler receives these statistics and sampled values, not the full dataset.",
  },
  modeler: {
    title: "Drafting the data model",
    text: "The Modeler is reading the profile and your request. It proposes a design, or asks when the data cannot settle a question.",
  },
  clarify: {
    title: "Sending your answers",
    text: "Your answers are on their way back to the Modeler.",
  },
  design_gate: {
    title: "Recording your decision",
    text: "The decision is being bound to this exact design version.",
  },
  codegen: {
    title: "Writing the dbt models",
    text: "Codegen is writing the silver and mart models for the approved design. The guard checks every file before it reaches the sandbox.",
  },
  execute: {
    title: "Building in the sandbox",
    text: "dbt compiles, runs and tests this code version on DuckDB in the isolated worker. A failing build goes back to Codegen within the repair budget.",
  },
};

const FALLBACK = {
  title: "Working",
  text: "The pipeline is running. This page refreshes on its own.",
};

function Working({ step }: { step: string | null }) {
  const copy = WORKING[step ?? ""] ?? FALLBACK;
  return (
    <section className="ws-page rn-page">
      <div>
        <h1 className="ws-h1">{copy.title}</h1>
        <p className="ws-lede">{copy.text}</p>
      </div>
      <div className="rn-working" role="status">
        <span className="rn-pulse" aria-hidden="true" />
        In progress &middot; this page updates automatically
      </div>
    </section>
  );
}

function Failed({ projectId, error }: { projectId: string; error: string | null }) {
  return (
    <section className="ws-page rn-page">
      <div>
        <h1 className="ws-h1">The run stopped</h1>
        <p className="ws-lede">Nothing was published. The error below was recorded with the run.</p>
      </div>
      <pre className="rn-error">{error ?? "No error message was recorded."}</pre>
      <div className="rn-actions">
        <button
          type="button"
          className="lp-button small"
          onClick={() => navigate({ name: "upload", projectId })}
        >
          Start a new run
        </button>
      </div>
    </section>
  );
}

function RunBody({
  projectId,
  run,
  canDecide,
  onRunChange,
  onStale,
}: {
  projectId: string;
  run: Run;
  canDecide: boolean;
  onRunChange: (run: Run) => void;
  onStale: () => void;
}) {
  const pending = run.pending;
  if (run.status === "failed") {
    return <Failed projectId={projectId} error={run.error} />;
  }
  if (
    run.status === "waiting_clarification" &&
    pending?.kind === "clarification" &&
    run.interrupt_id
  ) {
    return (
      <ClarificationPanel
        key={run.interrupt_id}
        projectId={projectId}
        runId={run.id}
        interruptId={run.interrupt_id}
        questions={pending.questions}
        canAnswer={canDecide}
        onAnswered={onRunChange}
        onStale={onStale}
      />
    );
  }
  if (
    run.status === "waiting_design_approval" &&
    pending?.kind === "design_gate" &&
    run.interrupt_id
  ) {
    return (
      <DesignGatePage
        key={run.interrupt_id}
        projectId={projectId}
        runId={run.id}
        interruptId={run.interrupt_id}
        pending={pending}
        canDecide={canDecide}
        onDecided={onRunChange}
        onStale={onStale}
      />
    );
  }
  if (run.status === "running" || run.status === "waiting_job") {
    return <Working step={run.current_step} />;
  }
  return (
    <section className="page">
      <h2>Code review and publishing</h2>
      <p className="todo">
        TODO: gate 2 code review, publishing and dashboard links arrive in weeks 3 to 5.
      </p>
    </section>
  );
}

export function RunPage({ projectId, runId }: { projectId: string; runId: string }) {
  const { run, error, setRun, refresh } = useRunPolling(projectId, runId);
  const project = useProject(projectId);
  const canDecide = project?.roles.includes("engineer") ?? false;
  const status = run?.status;
  const updatedAt = run?.updated_at;
  const builds = useRunBuilds(projectId, runId, updatedAt);

  useEffect(() => {
    if (status && updatedAt) {
      recordRunStatus(projectId, runId, status, updatedAt);
    }
  }, [projectId, runId, status, updatedAt]);

  return (
    <div className="rn">
      <div className="ws-crumb rn-crumb">
        {project?.name ?? "Project"} / Run{" "}
        <span className="lp-mono">{runId.slice(0, SHORT_ID_LENGTH)}</span>
      </div>
      {error !== null && <LoadError error={error} onRetry={refresh} />}
      {run && <WorkflowSteps run={run} />}
      {run ? (
        <RunBody
          projectId={projectId}
          run={run}
          canDecide={canDecide}
          onRunChange={setRun}
          onStale={refresh}
        />
      ) : (
        error === null && <p className="ws-muted">Loading the run...</p>
      )}
      {builds.error !== null && <LoadError error={builds.error} onRetry={builds.refresh} />}
      {builds.attempts.length > 0 && <BuildLog attempts={builds.attempts} />}
    </div>
  );
}
