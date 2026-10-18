import { Fragment } from "react";
import { StarSchema } from "./StarSchema";

const CSV_ROWS = [
  { id: "100482", customer: "C-00412", at: "2026-10-02 09:14", amount: "58.00" },
  { id: "100482", customer: "C-00412", at: "2026-10-02 09:14", amount: "12.50" },
  { id: "100483", customer: "C-01977", at: "2026-10-02 09:21", amount: null },
  { id: "100484", customer: "C-00031", at: "2026-10-02 09:40", amount: "240.00" },
];

const CHECKS = [
  { label: "dbt compile", value: "passed", tone: "lp-ok" },
  { label: "Tests", value: "24 / 24", tone: "lp-ok" },
  { label: "Rewrite equivalence", value: "equal", tone: "lp-ok" },
  { label: "Gate 2", value: "awaiting", tone: "lp-wait" },
];

function CsvPreview() {
  return (
    <div className="lp-paper lp-csv">
      <div className="lp-paper-bar">
        <span>orders.csv</span>
        <span>sample &middot; 9 cols</span>
      </div>
      <div className="lp-csv-grid">
        <span className="head">order_id</span>
        <span className="head">customer_id</span>
        <span className="head">order_ts</span>
        <span className="head num">amount</span>
        {CSV_ROWS.map((row) => (
          <Fragment key={`${row.id}-${row.amount}`}>
            <span>{row.id}</span>
            <span>{row.customer}</span>
            <span>{row.at}</span>
            {row.amount === null ? (
              <span className="num null" title="null">
                &empty;
              </span>
            ) : (
              <span className="num">{row.amount}</span>
            )}
          </Fragment>
        ))}
      </div>
    </div>
  );
}

function MartSql() {
  return (
    <div className="lp-code">
      <div className="dim">-- models/marts/fct_order_lines.sql</div>
      <div>
        <span className="kw">with</span> lines <span className="kw">as</span> (
      </div>
      <div>
        {"  "}
        <span className="kw">select</span> order_id, order_line,
      </div>
      <div>
        {"    "}
        <span className="jinja">{"{{ clean_amount('amount') }}"}</span>
      </div>
      <div>
        {"  "}
        <span className="kw">from</span> <span className="jinja">{"{{ ref('slv_orders') }}"}</span>
      </div>
      <div>
        {"  "}
        <span className="kw">where</span> status {"<>"} <span className="str">'cancelled'</span>)
      </div>
    </div>
  );
}

function VerificationCard() {
  return (
    <div className="lp-paper lp-check-card">
      <div className="lp-label">VERIFICATION</div>
      {CHECKS.map((check) => (
        <div key={check.label} className="lp-row">
          <span>{check.label}</span>
          <span className={check.tone}>{check.value}</span>
        </div>
      ))}
    </div>
  );
}

export function Hero({ onOpenWorkspace }: { onOpenWorkspace: () => void }) {
  return (
    <section className="lp-wrap lp-hero">
      <div className="lp-hero-grid">
        <div className="lp-hero-copy">
          <div className="lp-eyebrow">AI-POWERED DATA ENGINEERING</div>
          <div>
            <h1>From Raw CSV to Verified Data Warehouse.</h1>
            <p className="lp-hero-lede">
              Turn raw datasets and natural-language requirements into tested dbt pipelines,
              optimized transformations, and production-ready BI dashboards with human approval at
              every critical step.
            </p>
            <div className="lp-actions">
              <button type="button" className="lp-button" onClick={onOpenWorkspace}>
                Open Workspace &#8599;
              </button>
              <a href="#workflow" className="lp-button-outline">
                Explore Workflow
              </a>
            </div>
          </div>
        </div>
        <div
          className="lp-hero-art"
          role="img"
          aria-label="Illustrative composition: CSV preview, star schema, dbt code and verification summary"
        >
          <CsvPreview />
          <div className="lp-paper lp-schema-card">
            <div className="lp-caption">star schema &middot; dsn-3</div>
            <StarSchema variant="hero" />
          </div>
          <MartSql />
          <VerificationCard />
          <div className="lp-art-note">Illustrative sample data</div>
        </div>
      </div>
      <div aria-hidden="true" className="lp-block big" />
      <div aria-hidden="true" className="lp-block small" />
    </section>
  );
}
