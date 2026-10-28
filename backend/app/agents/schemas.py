from typing import Literal

from pydantic import BaseModel, Field

from app.ingest.filenames import required_filenames


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
    """Check business references and structural consistency before gate-1 approval."""
    problems: list[str] = []

    def require_names(label: str, names: list[str], *, allow_empty: bool = False) -> None:
        if not allow_empty and not names:
            problems.append(f"{label} cannot be empty")
        if any(not name.strip() for name in names):
            problems.append(f"{label} cannot contain blank names")
        if len(names) != len(set(names)):
            problems.append(f"{label} cannot contain duplicate names")

    mart_tables = [fact.name for fact in design.facts] + [
        dimension.name for dimension in design.dimensions
    ]
    require_names("Mart tables", mart_tables)
    sources = {source for fact in design.facts for source in fact.source_tables} | {
        dimension.source_table for dimension in design.dimensions
    }
    tables = set(mart_tables) | sources
    for fact in design.facts:
        require_names(f"Sources of {fact.name}", fact.source_tables)
        require_names(f"Measures of {fact.name}", fact.measures, allow_empty=True)
        require_names(f"Dimension keys of {fact.name}", fact.dimension_keys, allow_empty=True)
        if not fact.grain.strip():
            problems.append(f"Grain of {fact.name} cannot be blank")
    for dimension in design.dimensions:
        require_names(f"Business key of {dimension.name}", dimension.business_key)
        require_names(f"Attributes of {dimension.name}", dimension.attributes, allow_empty=True)
        if not dimension.source_table.strip():
            problems.append(f"Source of {dimension.name} cannot be blank")
    for key in design.keys:
        if key.table not in tables:
            problems.append(f"Key references unknown table {key.table}")
        require_names(f"Key columns of {key.table}", key.columns)
    for relationship in design.relationships:
        if relationship.child_table not in tables or relationship.parent_table not in tables:
            problems.append("Relationship references an unknown table")
        require_names("Child relationship columns", relationship.child_columns)
        require_names("Parent relationship columns", relationship.parent_columns)
        if len(relationship.child_columns) != len(relationship.parent_columns):
            problems.append("Relationship column counts must match")
    metric_names = [metric.name for metric in design.metrics]
    require_names("Metrics", metric_names)
    fact_names = {fact.name for fact in design.facts}
    for metric in design.metrics:
        if metric.fact_table not in fact_names:
            problems.append(f"Metric {metric.name} references an unknown fact")
        if not metric.definition.strip() or not metric.expression.strip():
            problems.append(f"Metric {metric.name} requires a definition and expression")
    for rule in design.cleaning_rules:
        if rule.table not in tables:
            problems.append(f"Cleaning rule references unknown table {rule.table}")
        if not rule.condition.strip():
            problems.append("Cleaning rule condition cannot be blank")
        if rule.action == "set_default" and rule.default_value is None:
            problems.append("A set_default rule requires a default value")
    require_names("Required files", design.update_policy.required_files)
    try:
        required_filenames(design.update_policy.required_files)
    except ValueError as exc:
        problems.append(str(exc))
    metrics = set(metric_names)
    require_names("Dashboard metrics", design.dashboard.metrics)
    if not set(design.dashboard.metrics) <= metrics:
        problems.append("Dashboard references an unknown metric")
    require_names("Dashboard card keys", [card.key for card in design.dashboard.cards])
    for card in design.dashboard.cards:
        if card.metric not in metrics or card.metric not in design.dashboard.metrics:
            problems.append(f"Card {card.key} references an unknown dashboard metric")
        if not card.title.strip():
            problems.append(f"Card {card.key} requires a title")
        if card.type in {"line", "bar"} and (
            not card.dimension or card.dimension not in design.dashboard.dimensions
        ):
            problems.append(f"Card {card.key} requires a declared dashboard dimension")
    for constraint in design.constraints:
        allowed = sources if constraint.layer == "silver" else set(mart_tables)
        if constraint.model not in allowed:
            problems.append(f"Constraint references unknown {constraint.layer} model")
        require_names(
            "Constraint columns", constraint.columns, allow_empty=constraint.kind == "expression"
        )
    justified = [
        *design.facts,
        *design.dimensions,
        *design.keys,
        *design.relationships,
        *design.metrics,
        *design.cleaning_rules,
        design.update_policy,
        design.dashboard,
    ]
    for choice in justified:
        if not choice.rationale.strip():
            problems.append("Every design decision requires a rationale")
        if choice.open_questions:
            problems.append("Resolve open questions before approving a design")
    return problems


def validate_modeler_output(output: ModelerOutput) -> list[str]:
    """Require a design or unambiguous questions; never accept both or neither."""
    if (output.design is not None) == bool(output.questions):
        return ["Return either a design or clarification questions, exclusively."]
    if output.design is not None:
        return validate_design(output.design)
    questions = [question.question for question in output.questions]
    if any(not question.strip() for question in questions):
        return ["Clarification questions cannot be blank"]
    if len(questions) != len(set(questions)):
        return ["Clarification questions must be distinct"]
    if any(not question.why.strip() for question in output.questions):
        return ["Clarification questions require a reason"]
    return []
