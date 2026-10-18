import { useState } from "react";
import type { RunStatus } from "../api/types";
import { LoadError } from "../components/workspace/LoadError";
import { useProject, useProjects } from "../hooks/useProjects";
import { discardDraft, forgetRun, type SavedRun, type UploadDraft, useProgress } from "../progress";
import { navigate } from "../router";

const SHORT_ID_LENGTH = 8;

type Tone = "run" | "warn" | "ok" | "bad" | "muted";

const STAGE: Record<RunStatus, { label: string; tone: Tone }> = {
  running: { label: "Running", tone: "run" },
  waiting_job: { label: "Running in sandbox", tone: "run" },
  waiting_clarification: { label: "Needs your answers", tone: "warn" },
  waiting_design_approval: { label: "Gate 1 awaiting review", tone: "warn" },
  waiting_code_approval: { label: "Gate 2 awaiting review", tone: "warn" },
  published: { label: "Published", tone: "ok" },
  failed: { label: "Failed", tone: "bad" },
};

const AWAITING: ReadonlySet<RunStatus> = new Set<RunStatus>([
  "waiting_clarification",
  "waiting_design_approval",
  "waiting_code_approval",
]);

function formatWhen(iso: string | null): string {
  if (!iso) {
    return "Not opened yet";
  }
  return new Date(iso).toLocaleString([], {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function stageOf(run: SavedRun): { label: string; tone: Tone } {
  return run.status ? STAGE[run.status] : { label: "Not opened yet", tone: "muted" };
}

function DraftCard({ draft, projectId }: { draft: UploadDraft; projectId: string }) {
  const files = draft.files.length;
  return (
    <div className="ws-panel pj-draft">
      <div>
        <div className="ws-strong">Draft upload</div>
        <div className="ws-sub">
          {files} file{files === 1 ? "" : "s"} uploaded &middot;{" "}
          {draft.requirement.trim() ? "requirement written" : "no requirement yet"} &middot; saved{" "}
          {formatWhen(draft.updatedAt)}
        </div>
      </div>
      <div className="ws-actions">
        <button
          type="button"
          className="lp-button small"
          onClick={() => navigate({ name: "upload", projectId })}
        >
          Continue
        </button>
        <button type="button" className="ws-link" onClick={() => discardDraft(projectId)}>
          Discard
        </button>
      </div>
    </div>
  );
}

function RunRow({ run, unsent }: { run: SavedRun; unsent: boolean }) {
  const [confirming, setConfirming] = useState(false);
  const stage = stageOf(run);
  return (
    <tr>
      <td>
        <div className="lp-mono ws-strong">
          {run.runId.slice(0, SHORT_ID_LENGTH)}
          {unsent && <span className="pj-unsent">Unsent work</span>}
        </div>
        <div className="ws-sub pj-request">{run.requestText || "Opened from a link"}</div>
      </td>
      <td>
        <span className="ws-status">
          <span className={`ws-dot ${stage.tone}`} aria-hidden="true" />
          {stage.label}
        </span>
      </td>
      <td className="ws-muted">{formatWhen(run.updatedAt ?? run.createdAt)}</td>
      <td className="ws-cta">
        {confirming ? (
          <span className="pj-confirm">
            <span className="ws-muted">Remove from this list?</span>
            <button
              type="button"
              className="ws-link pj-danger"
              onClick={() => forgetRun(run.runId)}
            >
              Remove
            </button>
            <button type="button" className="ws-link" onClick={() => setConfirming(false)}>
              Keep
            </button>
          </span>
        ) : (
          <span className="pj-confirm">
            <button
              type="button"
              className="ws-link"
              onClick={() => navigate({ name: "run", projectId: run.projectId, runId: run.runId })}
            >
              Open
            </button>
            <button type="button" className="ws-link pj-quiet" onClick={() => setConfirming(true)}>
              Remove
            </button>
          </span>
        )}
      </td>
    </tr>
  );
}

export function ProjectPage({ projectId }: { projectId: string }) {
  const { error, reload } = useProjects();
  const project = useProject(projectId);
  const progress = useProgress();
  const runs = progress.runs.filter((run) => run.projectId === projectId);
  const draft = progress.drafts.find((item) => item.projectId === projectId) ?? null;
  const awaiting = runs.filter((run) => run.status && AWAITING.has(run.status)).length;

  const summary = [
    { label: "Runs on this device", value: String(runs.length) },
    { label: "Awaiting you", value: String(awaiting) },
    { label: "Review mode", value: project?.review_mode === "solo" ? "Individual" : "Team" },
    { label: "Your roles", value: project?.roles.join(" + ") ?? "..." },
  ];

  return (
    <section className="ws-page">
      <div className="ws-crumb">Workspace / {project?.name ?? "Project"}</div>
      <div className="ws-title-row">
        <div>
          <h1 className="ws-h1">{project?.name ?? "Project"}</h1>
          <p className="ws-lede">
            {project?.review_mode === "solo"
              ? "Individual review mode: one person designs and approves; the history records that there was no independent review."
              : "Team review mode: design and code are approved by different people."}
          </p>
        </div>
        <button
          type="button"
          className="lp-button small"
          onClick={() => navigate({ name: "upload", projectId })}
        >
          New pipeline
        </button>
      </div>

      {error !== null && <LoadError error={error} onRetry={reload} />}

      <dl className="ws-summary">
        {summary.map((item) => (
          <div key={item.label}>
            <dt>{item.label}</dt>
            <dd className="pj-capitalize">{item.value}</dd>
          </div>
        ))}
      </dl>

      {draft && <DraftCard draft={draft} projectId={projectId} />}

      <div>
        <h2 className="ws-h2">Runs</h2>
        {runs.length === 0 ? (
          <p className="ws-muted">
            No runs yet. Start with <strong>New pipeline</strong>: upload a batch and describe what
            you need.
          </p>
        ) : (
          <div className="ws-table-wrap">
            <table className="ws-table">
              <thead>
                <tr>
                  <th scope="col">Run</th>
                  <th scope="col">Stage</th>
                  <th scope="col">Last update</th>
                  <th scope="col">
                    <span className="visually-hidden">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {runs.map((run) => (
                  <RunRow
                    key={run.runId}
                    run={run}
                    unsent={progress.work.some((item) => item.runId === run.runId)}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="ws-muted pj-note">
          Runs are remembered on this device. Removing one only hides it here: the run and its
          approval history stay on the server.
        </p>
      </div>
    </section>
  );
}
