import { useState } from "react";
import type { Project, ProjectRole, ReviewMode } from "../api/types";
import { LoadError } from "../components/workspace/LoadError";
import { NewProjectForm } from "../components/workspace/NewProjectForm";
import { useProjects } from "../hooks/useProjects";
import { navigate } from "../router";

const REVIEW_MODE_LABEL: Record<ReviewMode, string> = { team: "Team", solo: "Individual" };
const ROLE_LABEL: Record<ProjectRole, string> = { engineer: "Engineer", reviewer: "Reviewer" };

function countWithRole(projects: Project[], role: ProjectRole): number {
  return projects.filter((project) => project.roles.includes(role)).length;
}

function Summary({ projects }: { projects: Project[] }) {
  const items = [
    { label: "Projects", value: projects.length },
    { label: "As engineer", value: countWithRole(projects, "engineer") },
    { label: "As reviewer", value: countWithRole(projects, "reviewer") },
    {
      label: "Team review",
      value: projects.filter((project) => project.review_mode === "team").length,
    },
  ];
  return (
    <dl className="ws-summary">
      {items.map((item) => (
        <div key={item.label}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
        </div>
      ))}
    </dl>
  );
}

function ProjectTable({ projects }: { projects: Project[] }) {
  return (
    <div className="ws-table-wrap">
      <table className="ws-table">
        <thead>
          <tr>
            <th scope="col">Project</th>
            <th scope="col">Review mode</th>
            <th scope="col">Your roles</th>
            <th scope="col">
              <span className="visually-hidden">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {projects.map((project) => (
            <tr key={project.id}>
              <td>
                <div className="ws-strong">{project.name}</div>
                <div className="lp-mono ws-sub">{project.slug}</div>
              </td>
              <td>
                <span className="ws-status">
                  <span className={`ws-dot ${project.review_mode}`} aria-hidden="true" />
                  {REVIEW_MODE_LABEL[project.review_mode]}
                </span>
              </td>
              <td className="ws-muted">
                {project.roles.map((role) => ROLE_LABEL[role]).join(" + ")}
              </td>
              <td className="ws-cta">
                <button
                  type="button"
                  className="ws-link"
                  onClick={() => navigate({ name: "project", projectId: project.id })}
                >
                  Open
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ProjectsPage() {
  const { projects, error, reload, add } = useProjects();
  const [creating, setCreating] = useState(false);

  const onCreated = (project: Project) => {
    add(project);
    setCreating(false);
  };

  return (
    <section className="ws-page">
      <div className="ws-crumb">Workspace / Projects</div>
      <div className="ws-title-row">
        <div>
          <h1 className="ws-h1">Projects</h1>
          <p className="ws-lede">
            Each project holds its batches, pipelines and approval history. Roles are granted per
            project; the review mode decides whether design and code need different approvers.
          </p>
        </div>
        {!creating && (
          <button type="button" className="lp-button small" onClick={() => setCreating(true)}>
            New project
          </button>
        )}
      </div>

      {creating && <NewProjectForm onCreated={onCreated} onCancel={() => setCreating(false)} />}

      {error !== null && error !== undefined && <LoadError error={error} onRetry={reload} />}

      {projects === null && !error && <p className="ws-muted">Loading projects...</p>}

      {projects && (
        <>
          <Summary projects={projects} />
          <div>
            <h2 className="ws-h2">Your projects</h2>
            {projects.length === 0 ? (
              <p className="ws-muted">
                You are not a member of any project yet. Create one, or ask a project owner to add
                you.
              </p>
            ) : (
              <ProjectTable projects={projects} />
            )}
          </div>
        </>
      )}
    </section>
  );
}
