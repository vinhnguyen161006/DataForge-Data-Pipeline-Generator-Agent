import { useEffect, useState } from "react";
import { getApprovalHistory } from "../../api/client";
import type { ApprovalHistory } from "../../api/types";
import { useRunWork } from "../../hooks/useRunWork";
import { LoadError } from "../workspace/LoadError";

function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString([], {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function useDesignHistory(projectId: string, runId: string): ApprovalHistory[] {
  const [history, setHistory] = useState<ApprovalHistory[]>([]);
  useEffect(() => {
    let active = true;
    getApprovalHistory(projectId).then(
      (all) =>
        active &&
        setHistory(
          all
            .filter((entry) => entry.run_id === runId && entry.gate === "design")
            .sort((a, b) => b.created_at.localeCompare(a.created_at)),
        ),
      () => undefined,
    );
    return () => {
      active = false;
    };
  }, [projectId, runId]);
  return history;
}

interface ReturnDraft {
  returning: boolean;
  comment: string;
}

function isReturnDraft(value: unknown): value is ReturnDraft {
  return (
    typeof value === "object" &&
    value !== null &&
    "returning" in value &&
    typeof value.returning === "boolean" &&
    "comment" in value &&
    typeof value.comment === "string"
  );
}

function noReturn(value: ReturnDraft): boolean {
  return !value.returning && value.comment.trim() === "";
}

export interface ReviewActions {
  approve: () => void;
  startEdit: () => void;
  cancelEdit: () => void;
  sendBack: (comment: string) => void;
}

export function ReviewCard({
  projectId,
  runId,
  workScope,
  version,
  canDecide,
  editing,
  blockReason,
  busy,
  error,
  actions,
}: {
  projectId: string;
  runId: string;
  workScope: string;
  version: number;
  canDecide: boolean;
  editing: boolean;
  blockReason: string | null;
  busy: boolean;
  error: unknown;
  actions: ReviewActions;
}) {
  const history = useDesignHistory(projectId, runId);
  const work = useRunWork<ReturnDraft>(
    runId,
    workScope,
    () => ({ returning: false, comment: "" }),
    isReturnDraft,
    noReturn,
  );
  const { returning, comment } = work.value;
  const setReturning = (next: boolean) =>
    work.setValue((current) => ({ ...current, returning: next }));
  const setComment = (next: string) => work.setValue((current) => ({ ...current, comment: next }));

  return (
    <div className="gt-review">
      <div className="gt-review-head">
        <span className="gt-review-title">Design review</span>
        <span className="lp-mono gt-faint">
          v{version}
          {editing && " (edited)"}
        </span>
      </div>

      {canDecide && !returning && (
        <div className="gt-review-actions">
          <button
            type="button"
            className="lp-button small"
            disabled={blockReason !== null || busy}
            onClick={actions.approve}
          >
            {busy ? "Saving..." : editing ? `Approve edited v${version}` : `Approve v${version}`}
          </button>
          {editing ? (
            <button
              type="button"
              className="ws-button-outline"
              disabled={busy}
              onClick={actions.cancelEdit}
            >
              Discard edits
            </button>
          ) : (
            <button
              type="button"
              className="ws-button-outline"
              disabled={busy}
              onClick={actions.startEdit}
            >
              Edit design
            </button>
          )}
          {!editing && (
            <button
              type="button"
              className="lp-button-peach gt-small"
              disabled={busy}
              onClick={() => setReturning(true)}
            >
              Return for revision
            </button>
          )}
        </div>
      )}

      {canDecide && returning && (
        <div className="gt-return">
          <label htmlFor="return-comment" className="up-label">
            What should the Modeler change? <span className="up-required">*</span>
          </label>
          <textarea
            id="return-comment"
            className="up-textarea"
            rows={3}
            value={comment}
            disabled={busy}
            placeholder="Grain should be order line, not order."
            onChange={(event) => setComment(event.target.value)}
          />
          <div className="gt-review-actions">
            <button
              type="button"
              className="lp-button small"
              disabled={comment.trim().length === 0 || busy}
              onClick={() => actions.sendBack(comment.trim())}
            >
              {busy ? "Sending..." : "Send back to the Modeler"}
            </button>
            <button
              type="button"
              className="ws-link"
              disabled={busy}
              onClick={() => setReturning(false)}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {canDecide && blockReason && !returning && <p className="gt-hint">{blockReason}</p>}
      {!canDecide && (
        <p className="gt-hint">Design approval is an Engineer action under this project policy.</p>
      )}
      {error !== null && <LoadError error={error} />}

      {history.length > 0 && (
        <div className="gt-history">
          {history.map((entry) => (
            <span key={entry.id}>
              {entry.decision === "approved" ? "Approved" : "Returned"} &middot;{" "}
              {formatWhen(entry.created_at)}
              {entry.comment && <> &mdash; &ldquo;{entry.comment}&rdquo;</>}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
