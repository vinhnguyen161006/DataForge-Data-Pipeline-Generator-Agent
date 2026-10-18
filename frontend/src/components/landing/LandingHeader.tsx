import { Logo } from "./Logo";

const NAV = [
  { href: "#product", label: "Product" },
  { href: "#workflow", label: "Workflow" },
  { href: "#verification", label: "Verification" },
  { href: "#docs", label: "Documentation" },
];

export function LandingHeader({ onOpenWorkspace }: { onOpenWorkspace: () => void }) {
  return (
    <header className="lp-header">
      <button
        type="button"
        className="lp-brand"
        aria-label="DataForge home"
        onClick={() => window.scrollTo({ top: 0 })}
      >
        <Logo />
        <span className="lp-brand-name">DataForge</span>
      </button>
      <nav aria-label="Primary" className="lp-nav">
        {NAV.map((item) => (
          <a key={item.href} href={item.href}>
            {item.label}
          </a>
        ))}
      </nav>
      <button type="button" className="lp-button small" onClick={onOpenWorkspace}>
        Open Workspace
      </button>
    </header>
  );
}
