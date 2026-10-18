import { Fragment } from "react";

const PILLARS = [
  "Evidence-backed profiling",
  "Human-approved models",
  "Executed tests",
  "Measured SQL rewrites",
  "Reproducible exports",
];

export function ProductSection() {
  return (
    <section id="product" className="lp-product">
      <h2 className="lp-title">Engineering Pipelines You Can Verify.</h2>
      <p className="lp-text">
        DataForge automates the repetitive part of building a warehouse, profiling files, drafting a
        model, writing dbt, wiring tests and schedules. The decisions that carry business meaning,
        and the decision to publish, stay with your engineers and reviewers.
      </p>
      <p className="lp-text last">
        Every output is executed in a sandbox, tested against expected results, and bound to an
        exact version before anyone is asked to approve it.
      </p>
      <div className="lp-pillars">
        {PILLARS.map((pillar, index) => (
          <Fragment key={pillar}>
            {index > 0 && <span className="sep">/</span>}
            <span>{pillar}</span>
          </Fragment>
        ))}
      </div>
      <a href="#workflow" className="lp-button-quiet">
        See the workflow
      </a>
    </section>
  );
}
