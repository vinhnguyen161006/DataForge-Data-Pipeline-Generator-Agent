import type { ReactNode } from "react";
import type { CardSpec, DataDesign, Justified } from "../../api/types";

export interface Decision {
  index: string;
  topic: string;
  lines: ReactNode[];
  why: string[];
  open: string[];
}

export interface OpenQuestion {
  where: string;
  question: string;
}

export interface Entity {
  name: string;
  kind: "fact" | "dimension";
  summary: ReactNode;
  fields: { name: string; role: string; note: string }[];
}

const CARD_LABEL: Record<CardSpec["type"], string> = { kpi: "KPI", line: "Line", bar: "Bar" };

function openOf(items: Justified[]): string[] {
  return items.flatMap((item) => item.open_questions);
}

function whyOf(items: Justified[]): string[] {
  return items.map((item) => item.rationale).filter((text) => text.trim().length > 0);
}

function list(values: string[]): string {
  return values.join(", ");
}

function decision(
  position: number,
  topic: string,
  lines: ReactNode[],
  items: Justified[],
): Decision {
  return {
    index: String(position).padStart(2, "0"),
    topic,
    lines,
    why: whyOf(items),
    open: openOf(items),
  };
}

export function decisionsOf(design: DataDesign): Decision[] {
  const keyLines = design.keys.map((key) => (
    <>
      <code>{key.table}</code> ({list(key.columns)}) &middot; {key.kind} key
    </>
  ));
  const relationshipLines = design.relationships.map((relation) => (
    <>
      <code>
        {relation.child_table}.{list(relation.child_columns)}
      </code>{" "}
      &rarr;{" "}
      <code>
        {relation.parent_table}.{list(relation.parent_columns)}
      </code>{" "}
      &middot; {relation.cardinality.replaceAll("_", " ")}
    </>
  ));
  const cleaningLines =
    design.cleaning_rules.length === 0
      ? ["No cleaning rules: every row is kept as loaded."]
      : design.cleaning_rules.map((rule) => (
          <>
            <code>{rule.table}</code>: <code>{rule.condition}</code> &rarr;{" "}
            {rule.action.replaceAll("_", " ")}
            {rule.default_value !== null && <> ({rule.default_value})</>}
          </>
        ));
  const policy = design.update_policy;
  const board = design.dashboard;

  return [
    decision(
      1,
      "Grain",
      design.facts.map((fact) => (
        <>
          <code>{fact.name}</code>: {fact.grain}
        </>
      )),
      design.facts,
    ),
    decision(
      2,
      "Keys & relationships",
      [...keyLines, ...relationshipLines],
      [...design.keys, ...design.relationships, ...design.dimensions],
    ),
    decision(
      3,
      "Metric semantics",
      design.metrics.map((metric) => (
        <>
          <code>{metric.name}</code> = <code>{metric.expression}</code> &middot; {metric.definition}
        </>
      )),
      design.metrics,
    ),
    decision(4, "Cleaning & invalid records", cleaningLines, design.cleaning_rules),
    decision(
      5,
      "Refresh strategy",
      [
        "Full snapshot replacement each run",
        <>Required files: {list(policy.required_files) || "none listed"}</>,
      ],
      [policy],
    ),
    decision(
      6,
      "Dashboard",
      [
        ...board.cards.map((card) => (
          <>
            {CARD_LABEL[card.type]} &middot; {card.title} &middot; <code>{card.metric}</code>
            {card.dimension && <> by {card.dimension}</>}
          </>
        )),
        <>Filters: {list(board.filters) || "none"}</>,
      ],
      [board],
    ),
  ];
}

export function openQuestionsOf(design: DataDesign): OpenQuestion[] {
  return decisionsOf(design).flatMap((item) =>
    item.open.map((question) => ({ where: item.topic, question })),
  );
}

export function entitiesOf(design: DataDesign): Entity[] {
  const facts: Entity[] = design.facts.map((fact) => ({
    name: fact.name,
    kind: "fact",
    summary: (
      <>
        Fact &middot; grain: <span className="gt-ink">{fact.grain}</span>
      </>
    ),
    fields: [
      ...fact.dimension_keys.map((name) => ({ name, role: "key", note: "joins a dimension" })),
      ...fact.measures.map((name) => ({ name, role: "measure", note: "" })),
    ],
  }));
  const dimensions: Entity[] = design.dimensions.map((dimension) => ({
    name: dimension.name,
    kind: "dimension",
    summary: (
      <>
        Dimension &middot; source: <span className="gt-ink">{dimension.source_table}</span>
      </>
    ),
    fields: [
      ...dimension.business_key.map((name) => ({ name, role: "business key", note: "" })),
      ...dimension.attributes.map((name) => ({ name, role: "attribute", note: "" })),
    ],
  }));
  return [...facts, ...dimensions];
}
