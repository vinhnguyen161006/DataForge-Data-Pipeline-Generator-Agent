import type { ReactNode } from "react";
import { StarSchema } from "./StarSchema";

const COLUMNS = [
  { name: "order_id", distinct: 66, nulls: "0.0%", warn: false },
  { name: "customer_id", distinct: 13, nulls: "0.0%", warn: false },
  { name: "amount", distinct: 20, nulls: "0.2%", warn: true },
  { name: "status", distinct: 2, nulls: "0.0%", warn: false },
  { name: "region", distinct: 2, nulls: "1.4%", warn: true },
];

const PROJECT_TREE = [
  { path: "models/", indent: false, count: null },
  { path: "bronze/", indent: true, count: "3 models" },
  { path: "silver/", indent: true, count: "3 models" },
  { path: "marts/", indent: true, count: "4 models" },
  { path: "tests/", indent: false, count: "24 tests" },
  { path: "macros/clean_amount.sql", indent: false, count: null },
  { path: "dags/orders_weekly.py", indent: false, count: null },
  { path: "dbt_project.yml", indent: false, count: null },
];

function ProfileTile() {
  return (
    <div className="lp-tile">
      <div className="lp-caption">orders.csv &middot; columns</div>
      <div className="lp-columns">
        {COLUMNS.map((column) => (
          <ColumnRow key={column.name} {...column} />
        ))}
      </div>
      <div className="lp-tile-foot">
        Candidate key <span className="lp-mono">(order_id, order_line)</span> &middot; unique in
        100% of rows
      </div>
    </div>
  );
}

function ColumnRow({
  name,
  distinct,
  nulls,
  warn,
}: {
  name: string;
  distinct: number;
  nulls: string;
  warn: boolean;
}) {
  return (
    <>
      <span>{name}</span>
      <span className="lp-meter">
        <span style={{ width: `${distinct}%` }} />
      </span>
      <span className={warn ? "rate warn" : "rate"}>{nulls}</span>
    </>
  );
}

function ModelTile() {
  return (
    <div className="lp-tile">
      <div className="lp-caption">proposed design &middot; dsn-3</div>
      <StarSchema variant="tile" />
      <div className="lp-tile-foot">
        Grain &middot; keys &middot; metrics &middot; cleaning &middot; refresh &middot; dashboard
      </div>
    </div>
  );
}

function GenerateTile() {
  return (
    <div className="lp-tile lp-tree">
      <div className="lp-caption">orders_weekly / v7</div>
      {PROJECT_TREE.map((entry) => (
        <div key={entry.path} className={entry.indent ? "indent" : undefined}>
          {entry.path} {entry.count && <span className="count">{entry.count}</span>}
        </div>
      ))}
    </div>
  );
}

function VerifyTile() {
  return (
    <div className="lp-tile">
      <div className="lp-caption">verification &middot; v7</div>
      <div className="lp-row">
        <span>Expected output</span>
        <span className="lp-ok">match</span>
      </div>
      <div className="lp-row">
        <span>Rewrite equivalence</span>
        <span className="lp-ok">equal</span>
      </div>
      <div className="lp-row">
        <span>Candidates rejected</span>
        <span className="lp-bad">2 of 3</span>
      </div>
      <div className="lp-bars">
        <span className="lp-step-number">median runtime</span>
        <span>
          <span className="lp-bar orig" />
          orig
        </span>
        <span>
          <span className="lp-bar rewrite" />
          rewrite
        </span>
      </div>
    </div>
  );
}

const STEPS: { number: string; name: string; text: string; tile: ReactNode }[] = [
  {
    number: "01",
    name: "Profile",
    text: "Column statistics, candidate keys and relationship evidence.",
    tile: <ProfileTile />,
  },
  {
    number: "02",
    name: "Model",
    text: "A proposed grain, facts, dimensions, measures and cleaning rules.",
    tile: <ModelTile />,
  },
  {
    number: "03",
    name: "Generate",
    text: "Bronze, silver and mart dbt models, tests and an Airflow DAG.",
    tile: <GenerateTile />,
  },
  {
    number: "04",
    name: "Verify",
    text: "Test results, execution metrics, SQL equivalence and repeated benchmarks before review.",
    tile: <VerifyTile />,
  },
];

export function WorkflowSection() {
  return (
    <section id="workflow" className="lp-wrap lp-section">
      <h2 className="lp-title">The Workflow</h2>
      <div className="lp-steps">
        {STEPS.map((step) => (
          <div key={step.number} className="lp-step">
            {step.tile}
            <div className="lp-step-number">{step.number}</div>
            <div className="lp-step-name">{step.name}</div>
            <p>{step.text}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
