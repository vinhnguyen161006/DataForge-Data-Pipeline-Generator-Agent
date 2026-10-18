import { useEffect } from "react";
import { WorkspaceShell } from "./components/workspace/WorkspaceShell";
import { useAuthToken } from "./hooks/useAuthToken";
import { ProjectsProvider } from "./hooks/useProjects";
import { ExportPage } from "./pages/ExportPage";
import { LandingPage } from "./pages/LandingPage";
import { LoginPage } from "./pages/LoginPage";
import { ProjectPage } from "./pages/ProjectPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { RunPage } from "./pages/RunPage";
import { UploadPage } from "./pages/UploadPage";
import { Link, navigate, type Route, useRoute } from "./router";

const HOME: Route = { name: "projects" };

function Redirect({ to }: { to: Route }) {
  useEffect(() => {
    navigate(to, { replace: true });
  }, [to]);
  return null;
}

function NotFoundPage() {
  return (
    <section className="page">
      <h2>Page not found</h2>
      <Link to={HOME}>Back to projects</Link>
    </section>
  );
}

function AuthenticatedPage({ route }: { route: Route }) {
  switch (route.name) {
    case "landing":
      return <LandingPage />;
    case "login":
      return <Redirect to={HOME} />;
    case "projects":
      return <ProjectsPage />;
    case "project":
      return <ProjectPage key={route.projectId} projectId={route.projectId} />;
    case "upload":
      return <UploadPage key={route.projectId} projectId={route.projectId} />;
    case "run":
      return <RunPage key={route.runId} projectId={route.projectId} runId={route.runId} />;
    case "export":
      return <ExportPage key={route.runId} projectId={route.projectId} runId={route.runId} />;
    case "notFound":
      return <NotFoundPage />;
  }
}

export function App() {
  const route = useRoute();
  const signedIn = useAuthToken() !== null;
  if (route.name === "landing") {
    return <LandingPage />;
  }
  if (!signedIn) {
    return <LoginPage />;
  }
  return (
    <ProjectsProvider>
      <WorkspaceShell route={route}>
        <AuthenticatedPage route={route} />
      </WorkspaceShell>
    </ProjectsProvider>
  );
}
