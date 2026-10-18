import { type SubmitEvent, useState } from "react";
import { createProject } from "../../api/client";
import type { Project, ReviewMode } from "../../api/types";
import { slugify } from "../../slug";
import { LoadError } from "./LoadError";

const SLUG_PATTERN = "[a-z0-9]+(-[a-z0-9]+)*";

const REVIEW_MODE_HELP: Record<ReviewMode, string> = {
  team: "Team: design and code are approved by different people.",
  solo: "Individual: one person holds both roles; the history records that there was no independent review.",
};

export function NewProjectForm({
  onCreated,
  onCancel,
}: {
  onCreated: (project: Project) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [reviewMode, setReviewMode] = useState<ReviewMode>("team");
  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);

  const onNameChange = (value: string) => {
    setName(value);
    if (!slugEdited) {
      setSlug(slugify(value));
    }
  };

  const onSubmit = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      onCreated(await createProject({ name: name.trim(), slug, review_mode: reviewMode }));
    } catch (caught) {
      setError(caught);
      setSubmitting(false);
    }
  };

  return (
    <form className="ws-panel ws-form" onSubmit={onSubmit} aria-busy={submitting}>
      <h2 className="ws-h2">New project</h2>
      {error !== null && <LoadError error={error} />}
      <div className="ws-form-grid">
        <label className="ws-field">
          <span>Name</span>
          <input
            className="ws-input"
            required
            value={name}
            disabled={submitting}
            placeholder="Retail Analytics"
            onChange={(event) => onNameChange(event.target.value)}
          />
        </label>
        <label className="ws-field">
          <span>Slug</span>
          <input
            className="ws-input lp-mono"
            required
            pattern={SLUG_PATTERN}
            title="Lowercase letters, digits and single hyphens"
            value={slug}
            disabled={submitting}
            placeholder="retail-analytics"
            onChange={(event) => {
              setSlug(event.target.value);
              setSlugEdited(true);
            }}
          />
        </label>
        <label className="ws-field">
          <span>Review mode</span>
          <select
            className="ws-input"
            value={reviewMode}
            disabled={submitting}
            onChange={(event) => setReviewMode(event.target.value as ReviewMode)}
          >
            <option value="team">Team</option>
            <option value="solo">Individual</option>
          </select>
        </label>
      </div>
      <p className="ws-help">{REVIEW_MODE_HELP[reviewMode]}</p>
      <div className="ws-actions">
        <button type="submit" className="lp-button small" disabled={submitting}>
          {submitting ? "Creating..." : "Create project"}
        </button>
        <button type="button" className="ws-link" onClick={onCancel} disabled={submitting}>
          Cancel
        </button>
      </div>
    </form>
  );
}
