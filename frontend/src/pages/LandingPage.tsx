import "../landing.css";
import { GatesSection } from "../components/landing/GatesSection";
import { Hero } from "../components/landing/Hero";
import { LandingFooter } from "../components/landing/LandingFooter";
import { LandingHeader } from "../components/landing/LandingHeader";
import { ProductSection } from "../components/landing/ProductSection";
import { VerificationSection } from "../components/landing/VerificationSection";
import { WorkflowSection } from "../components/landing/WorkflowSection";
import { navigate } from "../router";

export function LandingPage() {
  const openWorkspace = () => navigate({ name: "projects" });
  return (
    <div className="lp">
      <LandingHeader onOpenWorkspace={openWorkspace} />
      <main>
        <Hero onOpenWorkspace={openWorkspace} />
        <ProductSection />
        <WorkflowSection />
        <VerificationSection onOpenWorkspace={openWorkspace} />
        <GatesSection />
      </main>
      <LandingFooter />
    </div>
  );
}
