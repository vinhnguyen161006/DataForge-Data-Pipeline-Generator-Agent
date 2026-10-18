const GROUPS = [
  {
    heading: "Product",
    links: [
      { label: "Overview", href: "#product" },
      { label: "Workflow", href: "#workflow" },
      { label: "Verification", href: "#verification" },
    ],
  },
  {
    heading: "Documentation",
    links: [
      { label: "Getting started", href: "#docs" },
      { label: "Approval gates", href: "#docs" },
      { label: "Export format", href: "#docs" },
      { label: "API reference", href: "#docs" },
    ],
  },
  {
    heading: "Project",
    links: [
      { label: "Architecture", href: "#docs" },
      { label: "Security model", href: "#docs" },
      { label: "Changelog", href: "#docs" },
    ],
  },
  {
    heading: "Repository",
    links: [
      { label: "Source", href: "#docs" },
      { label: "Report an issue", href: "#docs" },
    ],
  },
];

export function LandingFooter() {
  return (
    <footer id="docs" className="lp-footer">
      <div className="lp-footer-links">
        {GROUPS.map((group) => (
          <div key={group.heading}>
            <span className="heading">{group.heading}</span>
            {group.links.map((link) => (
              <a key={link.label} href={link.href}>
                {link.label}
              </a>
            ))}
          </div>
        ))}
      </div>
      <div className="lp-footer-legal">
        <span>&copy; 2026 DataForge</span>
        <span>Privacy &middot; Terms</span>
      </div>
    </footer>
  );
}
