import { useEffect } from "react";
import { logout } from "./api/client";
import { useAuthToken } from "./hooks/useAuthToken";
import { ExportPage } from "./pages/ExportPage";
import { LoginPage } from "./pages/LoginPage";
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
    case "login":
      return <Redirect to={HOME} />;
    case "projects":
      return <ProjectsPage />;
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
  const token = useAuthToken();
  const signedIn = token !== null;
  return (
    <div className="layout">
      <header className="header">
        <h1>
          <Link to={HOME} className="brand">
            DataForge
          </Link>
        </h1>
        {signedIn && (
          <nav>
            <Link to={HOME}>Projects</Link>
            <button type="button" onClick={logout}>
              Sign out
            </button>
          </nav>
        )}
      </header>
      <main>{signedIn ? <AuthenticatedPage route={route} /> : <LoginPage />}</main>
    </div>
  );
}
