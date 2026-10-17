import { type SubmitEvent, useEffect, useState } from "react";
import { createProject, listProjects } from "../api/client";
import type { Project, ReviewMode } from "../api/types";
import { errorText } from "../errors";
import { Link } from "../router";
import { slugify } from "../slug";

const REVIEW_MODE_HELP: Record<ReviewMode, string> = {
  team: "Team: the Reviewer must be a different person from the Engineer.",
  solo: "Solo: one person holds both roles; the log records that there was no independent review.",
};

function ProjectList({ projects }: { projects: Project[] }) {
  if (projects.length === 0) {
    return <p className="muted">No projects yet. Create the first one below.</p>;
  }
  return (
    <table className="table">
      <thead>
        <tr>
          <th>Name</th>
          <th>Slug</th>
          <th>Review mode</th>
          <th>Your roles</th>
        </tr>
      </thead>
      <tbody>
        {projects.map((project) => (
          <tr key={project.id}>
            <td>
              <Link to={{ name: "upload", projectId: project.id }}>{project.name}</Link>
            </td>
            <td>
              <code>{project.slug}</code>
            </td>
            <td>{project.review_mode}</td>
            <td>
              {project.roles.map((role) => (
                <span key={role} className="badge">
                  {role}
                </span>
              ))}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function CreateProjectForm({ onCreated }: { onCreated: (project: Project) => void }) {
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [reviewMode, setReviewMode] = useState<ReviewMode>("team");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onNameChange = (value: string) => {
    setName(value);
    if (!slugEdited) {
      setSlug(slugify(value));
    }
  };

  const onSlugChange = (value: string) => {
    setSlug(value);
    setSlugEdited(true);
  };

  const onSubmit = async (event: SubmitEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      onCreated(await createProject({ name: name.trim(), slug, review_mode: reviewMode }));
      setName("");
      setSlug("");
      setSlugEdited(false);
      setReviewMode("team");
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="form" onSubmit={onSubmit}>
      <h3>New project</h3>
      <label>
        Name
        <input required value={name} onChange={(event) => onNameChange(event.target.value)} />
      </label>
      <label>
        Slug
        <input
          required
          pattern="[a-z0-9]+(-[a-z0-9]+)*"
          title="Lowercase letters, digits and single hyphens"
          value={slug}
          onChange={(event) => onSlugChange(event.target.value)}
        />
      </label>
      <label>
        Review mode
        <select
          value={reviewMode}
          onChange={(event) => setReviewMode(event.target.value as ReviewMode)}
        >
          <option value="team">Team</option>
          <option value="solo">Solo</option>
        </select>
      </label>
      <p className="muted">{REVIEW_MODE_HELP[reviewMode]}</p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <button type="submit" className="primary" disabled={submitting}>
        {submitting ? "Creating..." : "Create project"}
      </button>
    </form>
  );
}

export function ProjectsPage() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    listProjects().then(
      (loaded) => active && setProjects(loaded),
      (caught: unknown) => active && setError(errorText(caught)),
    );
    return () => {
      active = false;
    };
  }, []);

  const onCreated = (project: Project) => {
    setProjects((current) => [project, ...(current ?? [])]);
  };

  return (
    <section className="page">
      <h2>Projects</h2>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {projects === null && !error && <p className="muted">Loading projects...</p>}
      {projects && <ProjectList projects={projects} />}
      <CreateProjectForm onCreated={onCreated} />
    </section>
  );
}
