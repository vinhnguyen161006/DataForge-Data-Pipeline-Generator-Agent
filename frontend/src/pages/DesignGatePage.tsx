import { useState } from "react";
import { ApiError, decideDesign } from "../api/client";
import type { DataDesign, DesignDecision, PendingDesignGate, Run } from "../api/types";
import { DesignEditor } from "../components/gate/DesignEditor";
import { ConstraintList, DecisionList, EntityPanel } from "../components/gate/DesignOverview";
import { openQuestionsOf } from "../components/gate/designView";
import { ReviewCard } from "../components/gate/ReviewCard";
import { validateDesign } from "../components/gate/validateDesign";
import { formatSavedAt, useRunWork } from "../hooks/useRunWork";
import { clearWork } from "../progress";

const HTTP_CONFLICT = 409;

function plural(count: number, noun: string): string {
  return `${count} ${noun}${count === 1 ? "" : "s"}`;
}

function OpenQuestions({ design }: { design: DataDesign }) {
  const questions = openQuestionsOf(design);
  if (questions.length === 0) {
    return null;
  }
  return (
    <fieldset className="rn-clarify">
      <legend>Open questions &middot; {plural(questions.length, "question")}</legend>
      <ul className="gt-open">
        {questions.map((item) => (
          <li key={`${item.where}-${item.question}`}>
            <span className="gt-faint">{item.where}:</span> {item.question}
          </li>
        ))}
      </ul>
      <p className="gt-hint">
        Edit the design to answer them, or return it to the Modeler with your guidance.
      </p>
    </fieldset>
  );
}

function isDesignDraft(value: unknown): value is DataDesign | null {
  return (
    value === null ||
    (typeof value === "object" &&
      "facts" in value &&
      Array.isArray(value.facts) &&
      "dashboard" in value &&
      typeof value.dashboard === "object")
  );
}

function noDraft(value: DataDesign | null): boolean {
  return value === null;
}

function returnScope(designVersionId: string): string {
  return `return:${designVersionId}`;
}

function blockReasonOf(design: DataDesign, editing: boolean): string | null {
  const problems = editing ? validateDesign(design) : [];
  if (problems.length > 0) {
    return `Fix ${plural(problems.length, "problem")} in the edited design: ${problems[0]}`;
  }
  const open = openQuestionsOf(design).length;
  if (open > 0) {
    return `Resolve ${plural(open, "open question")} to enable approval: edit the design or return it to the Modeler.`;
  }
  return null;
}

export function DesignGatePage({
  projectId,
  runId,
  interruptId,
  pending,
  canDecide,
  onDecided,
  onStale,
}: {
  projectId: string;
  runId: string;
  interruptId: string;
  pending: PendingDesignGate;
  canDecide: boolean;
  onDecided: (run: Run) => void;
  onStale: () => void;
}) {
  const work = useRunWork<DataDesign | null>(
    runId,
    `design:${pending.design_version_id}`,
    () => null,
    isDesignDraft,
    noDraft,
  );
  const draft = work.value;
  const setDraft = work.setValue;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const editing = draft !== null;
  const design = draft ?? pending.design;
  const open = openQuestionsOf(pending.design).length;

  const submit = async (body: Omit<DesignDecision, "interrupt_id" | "design_version_id">) => {
    setBusy(true);
    setError(null);
    try {
      const next = await decideDesign(projectId, runId, {
        ...body,
        interrupt_id: interruptId,
        design_version_id: pending.design_version_id,
      });
      work.clear();
      clearWork(runId, returnScope(pending.design_version_id));
      onDecided(next);
    } catch (caught) {
      setBusy(false);
      if (caught instanceof ApiError && caught.status === HTTP_CONFLICT) {
        onStale();
        return;
      }
      setError(caught);
    }
  };

  return (
    <section className="ws-page rn-page">
      <div>
        <h1 className="ws-h1">Proposed data model</h1>
        <p className="ws-lede">
          Design <span className="lp-mono gt-ink">v{pending.version}</span>
          {pending.edited_by_user ? ", edited by an Engineer" : ", proposed by the Modeler agent"}.
          Approval binds to this exact version; editing it creates a new version.
        </p>
      </div>

      {work.restoredAt && draft !== null && (
        <div className="ws-banner notice">
          Your unsent edits from {formatSavedAt(work.restoredAt)} were restored. Approve them or
          discard them.
        </div>
      )}

      <div role="status" className="ws-banner notice gt-gate-banner">
        <strong>Approval Gate 1</strong>
        <span>
          Code generation is paused until this design is approved.
          {open > 0 && ` ${plural(open, "open question")} to resolve.`}
        </span>
      </div>

      <div className="gt-columns">
        <EntityPanel key={pending.design_version_id} design={design} />
        <div className="gt-side">
          {editing ? (
            <DesignEditor design={design} onChange={setDraft} />
          ) : (
            <>
              <DecisionList design={design} />
              <OpenQuestions design={design} />
            </>
          )}
          <ReviewCard
            projectId={projectId}
            runId={runId}
            workScope={returnScope(pending.design_version_id)}
            version={pending.version}
            canDecide={canDecide}
            editing={editing}
            blockReason={blockReasonOf(design, editing)}
            busy={busy}
            error={error}
            actions={{
              approve: () =>
                submit(
                  draft ? { decision: "approve", edited_design: draft } : { decision: "approve" },
                ),
              startEdit: () => setDraft(structuredClone(pending.design)),
              cancelEdit: () => setDraft(null),
              sendBack: (comment) => submit({ decision: "return", comment }),
            }}
          />
        </div>
      </div>

      {!editing && <ConstraintList design={design} />}
    </section>
  );
}
