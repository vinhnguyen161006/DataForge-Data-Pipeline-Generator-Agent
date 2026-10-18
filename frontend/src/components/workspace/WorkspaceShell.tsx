import "../../landing.css";
import "../../workspace.css";
import type { ReactNode } from "react";
import { logout } from "../../api/client";
import { getAccountEmail } from "../../api/session";
import type { Project } from "../../api/types";
import { useProject } from "../../hooks/useProjects";
import { Link, navigate, type Route } from "../../router";
import { Logo } from "../landing/Logo";

const SHORT_ID_LENGTH = 8;

interface NavItem {
  label: string;
  to: Route;
}

interface NavGroup {
  heading: string;
  detail?: string;
  items: NavItem[];
}

function projectIdOf(route: Route): string | undefined {
  return "projectId" in route ? route.projectId : undefined;
}

function runIdOf(route: Route): string | undefined {
  return "runId" in route ? route.runId : undefined;
}

function initials(email: string | null): string {
  const local = (email ?? "").split("@")[0];
  const parts = local.split(/[._-]+/).filter(Boolean);
  const letters = parts.length > 1 ? parts[0][0] + parts[1][0] : local.slice(0, 2);
  return letters.toUpperCase() || "?";
}

function navGroups(route: Route, project: Project | undefined): NavGroup[] {
  const groups: NavGroup[] = [
    { heading: "Workspace", items: [{ label: "Projects", to: { name: "projects" } }] },
  ];
  const projectId = projectIdOf(route);
  if (projectId) {
    groups.push({
      heading: "Project",
      detail: project?.name ?? "...",
      items: [
        { label: "Overview", to: { name: "project", projectId } },
        { label: "Upload & request", to: { name: "upload", projectId } },
      ],
    });
  }
  const runId = runIdOf(route);
  if (projectId && runId) {
    groups.push({
      heading: "Run",
      detail: runId.slice(0, SHORT_ID_LENGTH),
      items: [
        { label: "Run status", to: { name: "run", projectId, runId } },
        { label: "Export", to: { name: "export", projectId, runId } },
      ],
    });
  }
  return groups;
}

function isCurrent(route: Route, target: Route): boolean {
  return (
    route.name === target.name &&
    projectIdOf(route) === projectIdOf(target) &&
    runIdOf(route) === runIdOf(target)
  );
}

function WorkspaceHeader({ route, project }: { route: Route; project: Project | undefined }) {
  const email = getAccountEmail();
  const runId = runIdOf(route);
  return (
    <header className="ws-header">
      <button
        type="button"
        className="lp-brand ws-brand"
        aria-label="DataForge public site"
        onClick={() => navigate({ name: "landing" })}
      >
        <Logo width={18} />
        <span className="lp-brand-name">DataForge</span>
      </button>
      <span className="ws-divider" aria-hidden="true" />
      <nav aria-label="Breadcrumb" className="ws-crumbs">
        {project ? (
          <Link to={{ name: "project", projectId: project.id }}>{project.name}</Link>
        ) : (
          <Link to={{ name: "projects" }}>All projects</Link>
        )}
        {runId && (
          <>
            <span className="ws-slash">/</span>
            <span className="lp-mono ws-run">{runId.slice(0, SHORT_ID_LENGTH)}</span>
          </>
        )}
      </nav>
      <div className="ws-spacer" />
      {project && <span className="ws-roles">{project.roles.join(" + ")}</span>}
      <span className="ws-avatar" title={email ?? undefined} role="img" aria-label="Account">
        {initials(email)}
      </span>
      <button type="button" className="ws-signout" onClick={logout}>
        Sign out
      </button>
    </header>
  );
}

function WorkspaceNav({ route, project }: { route: Route; project: Project | undefined }) {
  return (
    <nav aria-label="Workspace" className="ws-nav">
      {navGroups(route, project).map((group) => (
        <div key={`${group.heading}-${group.detail ?? ""}`} className="ws-nav-group">
          <div className="ws-nav-heading">
            {group.heading}
            {group.detail && <> &middot; {group.detail}</>}
          </div>
          {group.items.map((item) => (
            <button
              key={item.label}
              type="button"
              className="ws-nav-item"
              aria-current={isCurrent(route, item.to) ? "page" : undefined}
              onClick={() => navigate(item.to)}
            >
              {item.label}
            </button>
          ))}
        </div>
      ))}
    </nav>
  );
}

export function WorkspaceShell({ route, children }: { route: Route; children: ReactNode }) {
  const project = useProject(projectIdOf(route));
  return (
    <div className="lp ws">
      <WorkspaceHeader route={route} project={project} />
      <div className="ws-body">
        <WorkspaceNav route={route} project={project} />
        <main className="ws-main">{children}</main>
      </div>
    </div>
  );
}
