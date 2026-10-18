from app.agents.schemas import (
    CardSpec,
    DashboardRequirements,
    DataDesign,
    FactTable,
    KeyDefinition,
    MetricDefinition,
    UpdatePolicy,
)
from app.profiler.schemas import ColumnProfile, DataProfile, TableProfile


def minimal_design() -> DataDesign:
    return DataDesign(
        facts=[
            FactTable(
                name="fct_registration",
                grain="one student registration in one module presentation",
                source_tables=["studentRegistration"],
                measures=["registrations"],
                dimension_keys=["id_student"],
                rationale="The request asks for registration counts",
            )
        ],
        dimensions=[],
        keys=[
            KeyDefinition(
                table="studentRegistration",
                columns=["code_module", "code_presentation", "id_student"],
                kind="composite",
                rationale="Unique in the profile",
            )
        ],
        relationships=[],
        metrics=[
            MetricDefinition(
                name="registrations",
                definition="Number of registrations",
                expression="count(*)",
                fact_table="fct_registration",
                rationale="Directly requested",
            )
        ],
        cleaning_rules=[],
        update_policy=UpdatePolicy(required_files=["studentRegistration.csv"], rationale="One"),
        dashboard=DashboardRequirements(
            metrics=["registrations"],
            dimensions=[],
            filters=[],
            cards=[
                CardSpec(key="kpi_reg", title="Registrations", type="kpi", metric="registrations")
            ],
            rationale="Single KPI",
        ),
        constraints=[],
    )


def minimal_profile() -> DataProfile:
    return DataProfile(
        tables=[
            TableProfile(
                name="student_registration",
                source_file="studentRegistration.csv",
                row_count=3,
                columns=[
                    ColumnProfile(
                        name="id_student",
                        inferred_type="BIGINT",
                        row_count=3,
                        null_ratio=0.0,
                        distinct_count=3,
                    )
                ],
            )
        ],
        key_candidates=[],
        relationship_candidates=[],
    )
