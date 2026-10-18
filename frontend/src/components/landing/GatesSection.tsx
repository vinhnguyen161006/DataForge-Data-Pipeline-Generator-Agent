import { Fragment } from "react";

interface GateState {
  id: string;
  hash?: string;
  label: string;
  note?: string;
  frame: "draft" | "checked" | "final";
  tone: "" | "ok" | "wait" | "teal";
}

interface Gate {
  name: string;
  topic: string;
  role: string;
  states: GateState[];
  text: string;
}

const GATES: Gate[] = [
  {
    name: "Gate 1",
    topic: "Design",
    role: "ENGINEER",
    states: [
      { id: "dsn-3", label: "Proposed", note: "mutable", frame: "draft", tone: "wait" },
      {
        id: "dsn-3",
        hash: "a41f9c",
        label: "Approved",
        note: "immutable",
        frame: "final",
        tone: "ok",
      },
    ],
    text: "Grain, keys, metric semantics, cleaning rules, refresh strategy and dashboard metrics. Open questions block approval.",
  },
  {
    name: "Gate 2",
    topic: "Code & results",
    role: "REVIEWER",
    states: [
      { id: "v7", label: "Generated", frame: "draft", tone: "" },
      { id: "v7", label: "Verified", frame: "checked", tone: "teal" },
      { id: "v7", hash: "8e2d1b0", label: "Approved", frame: "final", tone: "ok" },
    ],
    text: "Diff, tests, expected-output comparison, rewrite evidence and benchmarks. In team mode the reviewer must differ from the engineer.",
  },
];

function Dotted({ first, second }: { first: string; second?: string }) {
  return second ? (
    <>
      {first} &middot; {second}
    </>
  ) : (
    first
  );
}

function StateBox({ state }: { state: GateState }) {
  const frame = state.frame === "final" ? "lp-state" : `lp-state ${state.frame}`;
  return (
    <div className={frame}>
      <div className="lp-state-id">
        <Dotted first={state.id} second={state.hash} />
      </div>
      <div className={`lp-state-label ${state.tone}`}>
        <Dotted first={state.label} second={state.note} />
      </div>
    </div>
  );
}

export function GatesSection() {
  return (
    <section className="lp-wrap lp-section lp-gates">
      <h2 className="lp-title">Two Gates. Two Decisions.</h2>
      <p className="lp-gates-lede">
        The workflow pauses twice. Approving the design never approves the code, and any later
        change reopens review.
      </p>
      <div className="lp-gate-grid">
        {GATES.map((gate) => (
          <div key={gate.name} className="lp-gate">
            <div className="lp-gate-head">
              <span className="lp-gate-name">
                <Dotted first={gate.name} second={gate.topic} />
              </span>
              <span className="lp-gate-role">{gate.role}</span>
            </div>
            <div className="lp-gate-flow">
              {gate.states.map((state, index) => (
                <Fragment key={state.label}>
                  {index > 0 && <span className="arrow">&rarr;</span>}
                  <StateBox state={state} />
                </Fragment>
              ))}
            </div>
            <p>{gate.text}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
