import type { ReactNode } from "react";
import type {
  CardSpec,
  CleaningRule,
  Constraint,
  DataDesign,
  DimensionTable,
  FactTable,
  Justified,
  KeyDefinition,
  MetricDefinition,
  RelationshipDefinition,
} from "../../api/types";
import { ListEditor, ListField, SelectField, TextField } from "./fields";

const KEY_KINDS = ["primary", "business", "composite"] as const;
const CARDINALITIES = ["many_to_one", "one_to_one"] as const;
const CLEANING_ACTIONS = ["quarantine", "fail_pipeline", "set_default", "deduplicate"] as const;
const CARD_TYPES = ["kpi", "line", "bar"] as const;
const LAYERS = ["silver", "mart"] as const;
const CONSTRAINT_KINDS = [
  "not_null",
  "unique",
  "accepted_values",
  "relationship",
  "expression",
] as const;

const JUSTIFIED: Justified = { rationale: "", open_questions: [] };

const blankFact = (): FactTable => ({
  ...JUSTIFIED,
  name: "",
  grain: "",
  source_tables: [],
  measures: [],
  dimension_keys: [],
});
const blankDimension = (): DimensionTable => ({
  ...JUSTIFIED,
  name: "",
  business_key: [],
  source_table: "",
  attributes: [],
});
const blankKey = (): KeyDefinition => ({ ...JUSTIFIED, table: "", columns: [], kind: "primary" });
const blankRelationship = (): RelationshipDefinition => ({
  ...JUSTIFIED,
  child_table: "",
  child_columns: [],
  parent_table: "",
  parent_columns: [],
  cardinality: "many_to_one",
});
const blankMetric = (): MetricDefinition => ({
  ...JUSTIFIED,
  name: "",
  definition: "",
  expression: "",
  fact_table: "",
});
const blankRule = (): CleaningRule => ({
  ...JUSTIFIED,
  table: "",
  columns: [],
  condition: "",
  action: "quarantine",
  default_value: null,
});
const blankCard = (): CardSpec => ({
  key: "",
  title: "",
  type: "kpi",
  metric: "",
  dimension: null,
});
const blankConstraint = (): Constraint => ({
  layer: "mart",
  model: "",
  columns: [],
  kind: "not_null",
  params: {},
  evidence: null,
});

function Justification<T extends Justified>({
  item,
  onChange,
}: {
  item: T;
  onChange: (item: T) => void;
}) {
  return (
    <>
      <TextField
        label="Why"
        multiline
        value={item.rationale}
        onChange={(rationale) => onChange({ ...item, rationale })}
      />
      <ListField
        label="Open questions"
        value={item.open_questions}
        placeholder="None. Type a question and press Enter"
        onChange={(open_questions) => onChange({ ...item, open_questions })}
      />
    </>
  );
}

function Section({
  index,
  title,
  children,
}: {
  index: string;
  title: string;
  children: ReactNode;
}) {
  return (
    <fieldset className="gt-section">
      <legend>
        <span className="gt-section-index">{index}</span> {title}
      </legend>
      {children}
    </fieldset>
  );
}

function paramsToText(params: Constraint["params"]): string[] {
  return Object.entries(params).map(([name, value]) =>
    Array.isArray(value) ? `${name}=${value.join("|")}` : `${name}=${value}`,
  );
}

function textToParams(lines: string[]): Constraint["params"] {
  return Object.fromEntries(
    lines
      .filter((line) => line.includes("="))
      .map((line) => {
        const [name, ...rest] = line.split("=");
        const value = rest.join("=");
        return [name.trim(), value.includes("|") ? value.split("|") : value];
      }),
  );
}

export function DesignEditor({
  design,
  onChange,
}: {
  design: DataDesign;
  onChange: (design: DataDesign) => void;
}) {
  const set = <K extends keyof DataDesign>(key: K, value: DataDesign[K]) =>
    onChange({ ...design, [key]: value });
  const board = design.dashboard;
  const policy = design.update_policy;

  return (
    <div className="gt-editor">
      <Section index="01" title="Grain">
        <ListEditor
          items={design.facts}
          noun="fact"
          minimum={1}
          blank={blankFact}
          onChange={(facts) => set("facts", facts)}
          render={(fact, update) => (
            <>
              <TextField
                label="Name"
                mono
                value={fact.name}
                onChange={(name) => update({ ...fact, name })}
              />
              <TextField
                label="Grain: what exactly is one row"
                multiline
                value={fact.grain}
                onChange={(grain) => update({ ...fact, grain })}
              />
              <ListField
                label="Source tables"
                value={fact.source_tables}
                onChange={(source_tables) => update({ ...fact, source_tables })}
              />
              <ListField
                label="Measures"
                value={fact.measures}
                onChange={(measures) => update({ ...fact, measures })}
              />
              <ListField
                label="Dimension keys"
                value={fact.dimension_keys}
                onChange={(dimension_keys) => update({ ...fact, dimension_keys })}
              />
              <Justification item={fact} onChange={update} />
            </>
          )}
        />
      </Section>

      <Section index="02" title="Keys & relationships">
        <h4 className="gt-subhead">Keys</h4>
        <ListEditor
          items={design.keys}
          noun="key"
          minimum={1}
          blank={blankKey}
          onChange={(keys) => set("keys", keys)}
          render={(key, update) => (
            <>
              <div className="gt-row">
                <TextField
                  label="Table"
                  mono
                  value={key.table}
                  onChange={(table) => update({ ...key, table })}
                />
                <SelectField
                  label="Kind"
                  value={key.kind}
                  options={KEY_KINDS}
                  onChange={(kind) => update({ ...key, kind })}
                />
              </div>
              <ListField
                label="Columns"
                value={key.columns}
                onChange={(columns) => update({ ...key, columns })}
              />
              <Justification item={key} onChange={update} />
            </>
          )}
        />
        <h4 className="gt-subhead">Relationships</h4>
        <ListEditor
          items={design.relationships}
          noun="relationship"
          blank={blankRelationship}
          onChange={(relationships) => set("relationships", relationships)}
          render={(relation, update) => (
            <>
              <div className="gt-row">
                <TextField
                  label="Child table"
                  mono
                  value={relation.child_table}
                  onChange={(child_table) => update({ ...relation, child_table })}
                />
                <TextField
                  label="Parent table"
                  mono
                  value={relation.parent_table}
                  onChange={(parent_table) => update({ ...relation, parent_table })}
                />
              </div>
              <div className="gt-row">
                <ListField
                  label="Child columns"
                  value={relation.child_columns}
                  onChange={(child_columns) => update({ ...relation, child_columns })}
                />
                <ListField
                  label="Parent columns"
                  value={relation.parent_columns}
                  onChange={(parent_columns) => update({ ...relation, parent_columns })}
                />
              </div>
              <SelectField
                label="Cardinality"
                value={relation.cardinality}
                options={CARDINALITIES}
                onChange={(cardinality) => update({ ...relation, cardinality })}
              />
              <Justification item={relation} onChange={update} />
            </>
          )}
        />
        <h4 className="gt-subhead">Dimensions</h4>
        <ListEditor
          items={design.dimensions}
          noun="dimension"
          blank={blankDimension}
          onChange={(dimensions) => set("dimensions", dimensions)}
          render={(dimension, update) => (
            <>
              <div className="gt-row">
                <TextField
                  label="Name"
                  mono
                  value={dimension.name}
                  onChange={(name) => update({ ...dimension, name })}
                />
                <TextField
                  label="Source table"
                  mono
                  value={dimension.source_table}
                  onChange={(source_table) => update({ ...dimension, source_table })}
                />
              </div>
              <ListField
                label="Business key"
                value={dimension.business_key}
                onChange={(business_key) => update({ ...dimension, business_key })}
              />
              <ListField
                label="Attributes"
                value={dimension.attributes}
                onChange={(attributes) => update({ ...dimension, attributes })}
              />
              <Justification item={dimension} onChange={update} />
            </>
          )}
        />
      </Section>

      <Section index="03" title="Metric semantics">
        <ListEditor
          items={design.metrics}
          noun="metric"
          minimum={1}
          blank={blankMetric}
          onChange={(metrics) => set("metrics", metrics)}
          render={(metric, update) => (
            <>
              <div className="gt-row">
                <TextField
                  label="Name"
                  mono
                  value={metric.name}
                  onChange={(name) => update({ ...metric, name })}
                />
                <TextField
                  label="Fact table"
                  mono
                  value={metric.fact_table}
                  onChange={(fact_table) => update({ ...metric, fact_table })}
                />
              </div>
              <TextField
                label="Business definition"
                multiline
                value={metric.definition}
                onChange={(definition) => update({ ...metric, definition })}
              />
              <TextField
                label="SQL expression"
                mono
                value={metric.expression}
                onChange={(expression) => update({ ...metric, expression })}
              />
              <Justification item={metric} onChange={update} />
            </>
          )}
        />
      </Section>

      <Section index="04" title="Cleaning & invalid records">
        <ListEditor
          items={design.cleaning_rules}
          noun="rule"
          blank={blankRule}
          onChange={(cleaning_rules) => set("cleaning_rules", cleaning_rules)}
          render={(rule, update) => (
            <>
              <div className="gt-row">
                <TextField
                  label="Table"
                  mono
                  value={rule.table}
                  onChange={(table) => update({ ...rule, table })}
                />
                <SelectField
                  label="Action"
                  value={rule.action}
                  options={CLEANING_ACTIONS}
                  onChange={(action) => update({ ...rule, action })}
                />
              </div>
              <ListField
                label="Columns"
                value={rule.columns}
                onChange={(columns) => update({ ...rule, columns })}
              />
              <TextField
                label="Condition (SQL predicate for violating rows)"
                mono
                value={rule.condition}
                onChange={(condition) => update({ ...rule, condition })}
              />
              {rule.action === "set_default" && (
                <TextField
                  label="Default value"
                  mono
                  value={rule.default_value ?? ""}
                  onChange={(value) => update({ ...rule, default_value: value || null })}
                />
              )}
              <Justification item={rule} onChange={update} />
            </>
          )}
        />
      </Section>

      <Section index="05" title="Refresh strategy">
        <p className="gt-note">Full snapshot replacement is the only strategy in this release.</p>
        <ListField
          label="Required files"
          value={policy.required_files}
          onChange={(required_files) => set("update_policy", { ...policy, required_files })}
        />
        <Justification
          item={policy}
          onChange={(update_policy) => set("update_policy", update_policy)}
        />
      </Section>

      <Section index="06" title="Dashboard">
        <ListField
          label="Metrics"
          value={board.metrics}
          onChange={(metrics) => set("dashboard", { ...board, metrics })}
        />
        <ListField
          label="Dimensions"
          value={board.dimensions}
          onChange={(dimensions) => set("dashboard", { ...board, dimensions })}
        />
        <ListField
          label="Filters"
          value={board.filters}
          onChange={(filters) => set("dashboard", { ...board, filters })}
        />
        <ListEditor
          items={board.cards}
          noun="card"
          minimum={1}
          blank={blankCard}
          onChange={(cards) => set("dashboard", { ...board, cards })}
          render={(card, update) => (
            <>
              <div className="gt-row">
                <TextField
                  label="Title"
                  value={card.title}
                  onChange={(title) => update({ ...card, title })}
                />
                <SelectField
                  label="Type"
                  value={card.type}
                  options={CARD_TYPES}
                  onChange={(type) => update({ ...card, type })}
                />
              </div>
              <div className="gt-row">
                <TextField
                  label="Metric"
                  mono
                  value={card.metric}
                  onChange={(metric) => update({ ...card, metric })}
                />
                <TextField
                  label="Dimension"
                  mono
                  value={card.dimension ?? ""}
                  onChange={(value) => update({ ...card, dimension: value || null })}
                />
              </div>
              <TextField
                label="Stable key"
                mono
                value={card.key}
                onChange={(key) => update({ ...card, key })}
              />
            </>
          )}
        />
        <Justification item={board} onChange={(dashboard) => set("dashboard", dashboard)} />
      </Section>

      <Section index="+" title="Constraints that become required tests">
        <ListEditor
          items={design.constraints}
          noun="constraint"
          blank={blankConstraint}
          onChange={(constraints) => set("constraints", constraints)}
          render={(constraint, update) => (
            <>
              <div className="gt-row">
                <SelectField
                  label="Layer"
                  value={constraint.layer}
                  options={LAYERS}
                  onChange={(layer) => update({ ...constraint, layer })}
                />
                <SelectField
                  label="Kind"
                  value={constraint.kind}
                  options={CONSTRAINT_KINDS}
                  onChange={(kind) => update({ ...constraint, kind })}
                />
              </div>
              <TextField
                label="Model"
                mono
                value={constraint.model}
                onChange={(model) => update({ ...constraint, model })}
              />
              <ListField
                label="Columns"
                value={constraint.columns}
                onChange={(columns) => update({ ...constraint, columns })}
              />
              <ListField
                label="Parameters (name=value, use | for lists)"
                value={paramsToText(constraint.params)}
                onChange={(lines) => update({ ...constraint, params: textToParams(lines) })}
              />
            </>
          )}
        />
      </Section>

      <Section index="+" title="Assumptions">
        <ListField
          label="Assumptions"
          value={design.assumptions}
          placeholder="Type an assumption and press Enter"
          onChange={(assumptions) => set("assumptions", assumptions)}
        />
      </Section>
    </div>
  );
}
