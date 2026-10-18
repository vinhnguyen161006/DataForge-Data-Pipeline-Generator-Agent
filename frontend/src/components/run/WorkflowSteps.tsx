import type { Run } from "../../api/types";

const STEPS = [
  "Upload",
  "Profile",
  "Model",
  "Gate 1",
  "Generate & run",
  "Optimize",
  "Gate 2",
  "Publish",
  "Dashboard",
  "Schedule",
];

const STEP_OF_NODE: Record<string, number> = {
  profile: 1,
  modeler: 2,
  clarify: 2,
  design_gate: 3,
  codegen: 4,
  execute: 4,
  optimize: 5,
  code_gate: 6,
  publish: 7,
  dashboard: 8,
};

type Tone = "ok" | "warn" | "run" | "bad" | "pending";

interface StepView {
  label: string;
  state: string;
  tone: Tone;
}

function currentStep(run: Run): number {
  if (run.status === "published") {
    return STEPS.length;
  }
  if (run.status === "waiting_clarification") {
    return STEP_OF_NODE.clarify;
  }
  if (run.status === "waiting_design_approval") {
    return STEP_OF_NODE.design_gate;
  }
  if (run.status === "waiting_code_approval") {
    return STEP_OF_NODE.code_gate;
  }
  return STEP_OF_NODE[run.current_step ?? "profile"] ?? 1;
}

function activeView(run: Run): Pick<StepView, "state" | "tone"> {
  switch (run.status) {
    case "failed":
      return { state: "Failed", tone: "bad" };
    case "waiting_clarification":
      return { state: "Needs input", tone: "warn" };
    case "waiting_design_approval":
    case "waiting_code_approval":
      return { state: "Awaiting approval", tone: "warn" };
    default:
      return { state: "Running", tone: "run" };
  }
}

function stepViews(run: Run): StepView[] {
  const current = currentStep(run);
  return STEPS.map((label, index) => {
    if (index < current) {
      return { label, state: "Done", tone: "ok" };
    }
    if (index === current) {
      return { label, ...activeView(run) };
    }
    return { label, state: "Pending", tone: "pending" };
  });
}

export function WorkflowSteps({ run }: { run: Run }) {
  return (
    <ol aria-label="Workflow progress" className="rn-steps">
      {stepViews(run).map((step) => (
        <li key={step.label} className={`rn-step ${step.tone}`}>
          <span className="rn-step-bar" aria-hidden="true" />
          <span className="rn-step-label">{step.label}</span>
          <span className="rn-step-state">{step.state}</span>
        </li>
      ))}
    </ol>
  );
}
