import { lazy, Suspense, useState } from "react";
import { DesignGatePage } from "./pages/DesignGatePage";
import { ExportPage } from "./pages/ExportPage";
import { LoginPage } from "./pages/LoginPage";
import { ProjectsPage } from "./pages/ProjectsPage";
import { RunPage } from "./pages/RunPage";
import { UploadPage } from "./pages/UploadPage";

const CodeGatePage = lazy(() =>
  import("./pages/CodeGatePage").then((module) => ({ default: module.CodeGatePage })),
);

const PAGES = {
  login: LoginPage,
  projects: ProjectsPage,
  upload: UploadPage,
  run: RunPage,
  design: DesignGatePage,
  code: CodeGatePage,
  export: ExportPage,
} as const;

type PageKey = keyof typeof PAGES;

export function App() {
  const [page, setPage] = useState<PageKey>("projects");
  const Page = PAGES[page];
  return (
    <div className="layout">
      <header className="header">
        <h1>DataForge</h1>
        <nav>
          {(Object.keys(PAGES) as PageKey[]).map((key) => (
            <button
              type="button"
              key={key}
              className={key === page ? "active" : ""}
              onClick={() => setPage(key)}
            >
              {key}
            </button>
          ))}
        </nav>
      </header>
      <main>
        <Suspense fallback={<p className="todo">Loading...</p>}>
          <Page />
        </Suspense>
      </main>
    </div>
  );
}
