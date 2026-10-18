import { Fragment } from "react";

const DIFF = [
  { kind: "del", text: "-  from slv_orders o" },
  { kind: "del", text: "-  where o.status <> 'cancelled'" },
  { kind: "add", text: "+  with lines as (select ... from slv_orders" },
  { kind: "add", text: "+    where status <> 'cancelled')" },
  { kind: "ctx", text: "   left join dim_customer c ..." },
];

const CHECKS = [
  { label: "Schema & row multiplicity", value: "equal", tone: "lp-ok" },
  { label: "NULLs, floats (1e-9), timestamps", value: "equal", tone: "lp-ok" },
  { label: "Median runtime, 5 runs each", value: "illustrative", tone: "" },
];

function Rings() {
  return (
    <svg
      aria-hidden="true"
      className="lp-rings"
      viewBox="0 0 600 500"
      fill="none"
      stroke="#E8E1D9"
      strokeWidth="1"
    >
      {[80, 140, 200, 260].map((radius) => (
        <circle key={radius} cx="420" cy="250" r={radius} />
      ))}
      <line x1="120" y1="250" x2="600" y2="250" />
      <line x1="420" y1="0" x2="420" y2="500" />
    </svg>
  );
}

function RewriteDiff() {
  return (
    <div className="lp-diff">
      <div className="lp-diff-bar">
        <span>fct_order_lines.sql &middot; generated &rarr; v7</span>
        <span>+5 &minus;3</span>
      </div>
      <div className="lp-diff-lines">
        {DIFF.map((line) => (
          <div key={line.text} className={line.kind}>
            {line.text}
          </div>
        ))}
      </div>
      <div className="lp-diff-checks">
        {CHECKS.map((check) => (
          <Fragment key={check.label}>
            <span>{check.label}</span>
            <span className={check.tone}>{check.value}</span>
          </Fragment>
        ))}
      </div>
    </div>
  );
}

export function VerificationSection({ onOpenWorkspace }: { onOpenWorkspace: () => void }) {
  return (
    <section id="verification" className="lp-wrap lp-section">
      <div className="lp-verify">
        <Rings />
        <div className="lp-verify-grid">
          <RewriteDiff />
          <div>
            <h2>Generated Is Not the Same as Verified.</h2>
            <p className="lp-text">
              An LLM can write SQL that looks right. DataForge runs it: dbt compiles, tests execute
              against the batch, and the output is compared with an expected reference.
            </p>
            <p className="lp-text last">
              A rewrite is kept only if its results are equivalent to the original schema,
              multiplicity, NULLs, floats, timestamps and it is measurably faster beyond run-to-run
              noise.
            </p>
            <button type="button" className="lp-button-peach" onClick={onOpenWorkspace}>
              View verification workflow
            </button>
          </div>
        </div>
      </div>
    </section>
  );
}
