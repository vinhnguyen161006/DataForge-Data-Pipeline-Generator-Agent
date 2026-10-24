from typing import Literal

from pydantic import BaseModel, Field


class Justified(BaseModel):
    rationale: str = Field(min_length=1, description="Short justification for this choice")
    open_questions: list[str] = Field(
        description="Unresolved questions for human review; use [] if none",
        default_factory=list,
    )


class FactTable(Justified):
    name: str
    grain: str = Field(
        min_length=1, description="Exactly what one row represents, including its identifying scope"
    )
    source_tables: list[str]
    measures: list[str]
    dimension_keys: list[str]
    rationale: str = Field(
        min_length=1,
        description="Why this fact table and its grain fit the business requirements",
    )


class DimensionTable(Justified):
    name: str
    business_key: list[str]
    source_table: str
    attributes: list[str]


class KeyDefinition(Justified):
    table: str
    columns: list[str]
    kind: Literal["primary", "business", "composite"]


class RelationshipDefinition(Justified):
    child_table: str
    child_columns: list[str]
    parent_table: str
    parent_columns: list[str]
    cardinality: Literal["many_to_one", "one_to_one"]


class MetricDefinition(Justified):
    name: str
    definition: str = Field(description="Business definition, e.g. revenue after refunds")
    expression: str = Field(description="SQL expression over the mart, e.g. sum(net_amount)")
    fact_table: str


class CleaningRule(Justified):
    table: str
    columns: list[str] = Field(default_factory=list)
    condition: str = Field(description="SQL predicate that identifies violating rows")
    action: Literal["quarantine", "fail_pipeline", "set_default", "deduplicate"]
    default_value: str | None = None


class UpdatePolicy(Justified):
    mode: Literal["snapshot_replace"] = "snapshot_replace"
    required_files: list[str] = Field(description="Files that must be present before a batch runs")


class CardSpec(BaseModel):
    key: str = Field(description="Stable logical key so retries update instead of duplicating")
    title: str
    type: Literal["kpi", "line", "bar"]
    metric: str
    dimension: str | None = None


class DashboardRequirements(Justified):
    metrics: list[str]
    dimensions: list[str]
    filters: list[str]
    cards: list[CardSpec] = Field(min_length=1)


class Constraint(BaseModel):
    layer: Literal["silver", "mart"]
    model: str
    columns: list[str]
    kind: Literal["not_null", "unique", "accepted_values", "relationship", "expression"]
    params: dict[str, str | list[str]] = Field(default_factory=dict)
    evidence: str | None = None


class DataDesign(BaseModel):
    """Reviewed at gate 1. Only approved `constraints` ever become mandatory tests."""

    facts: list[FactTable] = Field(min_length=1)
    dimensions: list[DimensionTable]
    keys: list[KeyDefinition] = Field(min_length=1)
    relationships: list[RelationshipDefinition]
    metrics: list[MetricDefinition] = Field(min_length=1)
    cleaning_rules: list[CleaningRule]
    update_policy: UpdatePolicy
    dashboard: DashboardRequirements
    constraints: list[Constraint]
    assumptions: list[str] = Field(default_factory=list)


class ClarificationQuestion(BaseModel):
    topic: Literal["grain", "metric", "key", "cleaning", "update", "dashboard", "other"]
    question: str
    why: str = Field(description="Why the statistical profile is not enough to decide")
    options: list[str] = Field(default_factory=list)


class ModelerOutput(BaseModel):
    design: DataDesign | None = None
    questions: list[ClarificationQuestion] = Field(default_factory=list)


class GeneratedFile(BaseModel):
    path: str = Field(description="Path inside the dbt project, e.g. models/mart/fct_orders.sql")
    content: str


class CodegenOutput(BaseModel):
    files: list[GeneratedFile]
    notes: list[str] = Field(default_factory=list)


class RewriteProposal(BaseModel):
    model_name: str
    candidate_sql: str
    idea: str


class OptimizerOutput(BaseModel):
    proposals: list[RewriteProposal]


def validate_design(design: DataDesign) -> list[str]:
    """Check table and metric references within a design."""
    errors: list[str] = []

    fact_names = {fact.name for fact in design.facts}
    dimension_names = {dimension.name for dimension in design.dimensions}
    table_names = fact_names | dimension_names
    metric_names = {metric.name for metric in design.metrics}

    for key in design.keys:
        if key.table not in table_names:
            errors.append(f"Key references unknown table: {key.table}")

    for relationship in design.relationships:
        if relationship.child_table not in table_names:
            errors.append(
                f"Relationship references unknown child table: {relationship.child_table}"
            )
        if relationship.parent_table not in table_names:
            errors.append(
                f"Relationship references unknown parent table: {relationship.parent_table}"
            )

    for metric in design.metrics:
        if metric.fact_table not in fact_names:
            errors.append(
                f"Metric '{metric.name}' references unknown fact table: {metric.fact_table}"
            )

    for metric_name in design.dashboard.metrics:
        if metric_name not in metric_names:
            errors.append(f"Dashboard references unknown metric: {metric_name}")

    for card in design.dashboard.cards:
        if card.metric not in metric_names:
            errors.append(f"Dashboard card '{card.key}' references unknown metric: {card.metric}")

    return errors


def validate_modeler_output(output: ModelerOutput) -> list[str]:
    """Require one output branch and validate any returned design."""
    has_design = output.design is not None
    has_questions = bool(output.questions)

    if has_design == has_questions:
        return ["Return either a design or clarification questions, exclusively."]

    if output.design is not None:
        return validate_design(output.design)

    return []
