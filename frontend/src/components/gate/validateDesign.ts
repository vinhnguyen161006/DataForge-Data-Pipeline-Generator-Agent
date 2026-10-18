import type { DataDesign, Justified } from "../../api/types";

function blank(value: string): boolean {
  return value.trim().length === 0;
}

function needsRationale(where: string, items: Justified[]): string[] {
  return items.flatMap((item, index) =>
    blank(item.rationale) ? [`${where} ${index + 1}: write why this choice was made.`] : [],
  );
}

function needsName(where: string, names: string[]): string[] {
  return names.flatMap((name, index) =>
    blank(name) ? [`${where} ${index + 1}: give it a name.`] : [],
  );
}

export function validateDesign(design: DataDesign): string[] {
  const problems: string[] = [];
  if (design.facts.length === 0) {
    problems.push("Grain: keep at least one fact table.");
  }
  if (design.keys.length === 0) {
    problems.push("Keys: keep at least one key.");
  }
  if (design.metrics.length === 0) {
    problems.push("Metrics: keep at least one metric.");
  }
  if (design.dashboard.cards.length === 0) {
    problems.push("Dashboard: keep at least one card.");
  }
  design.facts.forEach((fact, index) => {
    if (blank(fact.grain)) {
      problems.push(`Fact ${index + 1}: describe exactly what one row represents.`);
    }
  });
  design.dashboard.cards.forEach((card, index) => {
    if (blank(card.key) || blank(card.title) || blank(card.metric)) {
      problems.push(`Card ${index + 1}: fill in key, title and metric.`);
    }
  });
  return [
    ...problems,
    ...needsName(
      "Fact",
      design.facts.map((fact) => fact.name),
    ),
    ...needsName(
      "Dimension",
      design.dimensions.map((dimension) => dimension.name),
    ),
    ...needsName(
      "Metric",
      design.metrics.map((metric) => metric.name),
    ),
    ...needsRationale("Fact", design.facts),
    ...needsRationale("Dimension", design.dimensions),
    ...needsRationale("Key", design.keys),
    ...needsRationale("Relationship", design.relationships),
    ...needsRationale("Metric", design.metrics),
    ...needsRationale("Cleaning rule", design.cleaning_rules),
    ...needsRationale("Refresh strategy", [design.update_policy]),
    ...needsRationale("Dashboard", [design.dashboard]),
  ];
}
