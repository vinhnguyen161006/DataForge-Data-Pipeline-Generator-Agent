import { type MouseEvent, type ReactNode, useMemo, useSyncExternalStore } from "react";

export type Route =
  | { name: "login" }
  | { name: "projects" }
  | { name: "upload"; projectId: string }
  | { name: "run"; projectId: string; runId: string }
  | { name: "export"; projectId: string; runId: string }
  | { name: "notFound" };

const NAVIGATE_EVENT = "dataforge:navigate";
const PRIMARY_MOUSE_BUTTON = 0;

function decodeSegments(pathname: string): string[] | null {
  try {
    return pathname.split("/").filter(Boolean).map(decodeURIComponent);
  } catch {
    return null;
  }
}

export function parseRoute(pathname: string): Route {
  const segments = decodeSegments(pathname);
  if (segments === null) {
    return { name: "notFound" };
  }
  const [root, projectId, section, runId, action] = segments;
  if (segments.length === 0) {
    return { name: "projects" };
  }
  if (segments.length === 1 && root === "login") {
    return { name: "login" };
  }
  if (root !== "projects") {
    return { name: "notFound" };
  }
  if (segments.length === 1) {
    return { name: "projects" };
  }
  if (segments.length === 3 && section === "upload") {
    return { name: "upload", projectId };
  }
  if (segments.length === 4 && section === "runs") {
    return { name: "run", projectId, runId };
  }
  if (segments.length === 5 && section === "runs" && action === "export") {
    return { name: "export", projectId, runId };
  }
  return { name: "notFound" };
}

export function routePath(route: Route): string {
  switch (route.name) {
    case "login":
      return "/login";
    case "projects":
    case "notFound":
      return "/projects";
    case "upload":
      return `/projects/${encodeURIComponent(route.projectId)}/upload`;
    case "run":
      return `/projects/${encodeURIComponent(route.projectId)}/runs/${encodeURIComponent(route.runId)}`;
    case "export":
      return `${routePath({ ...route, name: "run" })}/export`;
  }
}

export function navigate(route: Route, options: { replace?: boolean } = {}): void {
  const path = routePath(route);
  if (options.replace) {
    window.history.replaceState(null, "", path);
  } else {
    window.history.pushState(null, "", path);
  }
  window.dispatchEvent(new Event(NAVIGATE_EVENT));
}

function subscribeLocation(listener: () => void): () => void {
  window.addEventListener("popstate", listener);
  window.addEventListener(NAVIGATE_EVENT, listener);
  return () => {
    window.removeEventListener("popstate", listener);
    window.removeEventListener(NAVIGATE_EVENT, listener);
  };
}

function currentPathname(): string {
  return window.location.pathname;
}

export function useRoute(): Route {
  const pathname = useSyncExternalStore(subscribeLocation, currentPathname);
  return useMemo(() => parseRoute(pathname), [pathname]);
}

function isPlainLeftClick(event: MouseEvent<HTMLAnchorElement>): boolean {
  return (
    event.button === PRIMARY_MOUSE_BUTTON &&
    !event.metaKey &&
    !event.ctrlKey &&
    !event.shiftKey &&
    !event.altKey
  );
}

export function Link({
  to,
  className,
  children,
}: {
  to: Route;
  className?: string;
  children: ReactNode;
}) {
  const onClick = (event: MouseEvent<HTMLAnchorElement>) => {
    if (isPlainLeftClick(event)) {
      event.preventDefault();
      navigate(to);
    }
  };
  return (
    <a href={routePath(to)} className={className} onClick={onClick}>
      {children}
    </a>
  );
}
