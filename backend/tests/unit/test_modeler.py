import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.llm import StructuredLLM
from app.agents.modeler import propose_design
from app.agents.schemas import (
    ClarificationQuestion,
    DataDesign,
    ModelerOutput,
    RelationshipDefinition,
)
from app.profiler.schemas import DataProfile


@pytest.fixture
def design() -> DataDesign:
    """Build a small design with consistent table and metric references."""
    return DataDesign.model_validate(
        {
            "facts": [
                {
                    "name": "fct_orders",
                    "grain": "One row per order.",
                    "source_tables": ["orders"],
                    "measures": ["amount"],
                    "dimension_keys": [],
                    "rationale": "The request explicitly requires order-level analysis.",
                }
            ],
            "dimensions": [],
            "keys": [
                {
                    "table": "fct_orders",
                    "columns": ["order_id"],
                    "kind": "primary",
                    "rationale": "Order ID identifies an order; approval is required.",
                }
            ],
            "relationships": [],
            "metrics": [
                {
                    "name": "revenue",
                    "definition": "Total paid order amount after refunds.",
                    "expression": "sum(amount)",
                    "fact_table": "fct_orders",
                    "rationale": "The user confirmed the meaning of amount.",
                }
            ],
            "cleaning_rules": [],
            "update_policy": {
                "mode": "snapshot_replace",
                "required_files": ["orders.csv"],
                "rationale": "Each input batch is a complete snapshot.",
            },
            "dashboard": {
                "metrics": ["revenue"],
                "dimensions": [],
                "filters": [],
                "cards": [
                    {
                        "key": "revenue_kpi",
                        "title": "Revenue",
                        "type": "kpi",
                        "metric": "revenue",
                    }
                ],
                "rationale": "A KPI displays the requested total revenue.",
            },
            "constraints": [],
            "assumptions": [],
        }
    )


def run_modeler(output: ModelerOutput) -> ModelerOutput:
    """Run the Modeler with a mocked LLM response."""
    llm = StructuredLLM(api_key="fake-key", model="fake-model")
    profile = DataProfile(
        tables=[],
        key_candidates=[],
        relationship_candidates=[],
    )

    with patch.object(
        StructuredLLM,
        "generate",
        new_callable=AsyncMock,
        return_value=output,
    ):
        return asyncio.run(
            propose_design(
                llm,
                request_text="Analyze orders.",
                profile=profile,
                answers=[],
            )
        )


def test_returns_questions_and_passes_context() -> None:
    """Preserve clarification questions and pass the supplied context."""
    output = ModelerOutput(
        questions=[
            ClarificationQuestion(
                topic="metric",
                question="Does amount include refunds?",
                why="The profile cannot establish the business meaning of amount.",
                options=["Before refunds", "After refunds"],
            )
        ]
    )
    llm = StructuredLLM(api_key="fake-key", model="fake-model")
    profile = DataProfile(
        tables=[],
        key_candidates=[],
        relationship_candidates=[],
    )
    answers = [{"question": "What is the grain?", "answer": "One row per order."}]

    with patch.object(
        StructuredLLM,
        "generate",
        new_callable=AsyncMock,
        return_value=output,
    ) as generate:
        result = asyncio.run(
            propose_design(
                llm,
                request_text="Analyze revenue.",
                profile=profile,
                answers=answers,
            )
        )

    assert result.design is None
    assert result.questions == output.questions
    generate.assert_awaited_once()

    call = generate.call_args
    assert call is not None
    assert call.kwargs["schema"] is ModelerOutput
    assert "snapshot_replace" in call.kwargs["system"]

    prompt = call.kwargs["prompt"]
    context = json.loads(prompt.split("\n\n", 1)[1])
    assert context["request_text"] == "Analyze revenue."
    assert context["profile"] == profile.model_dump(mode="json")
    assert context["answers"] == answers
    assert context["returned_design"] is None
    assert context["reviewer_feedback"] is None


def test_returns_valid_design(design: DataDesign) -> None:
    """Accept a design whose table and metric references are consistent."""
    result = run_modeler(ModelerOutput(design=design))

    assert result.design == design
    assert result.questions == []


@pytest.mark.parametrize("include_design", [False, True])
def test_rejects_invalid_output_branches(
    design: DataDesign,
    include_design: bool,
) -> None:
    """Reject neither branch or both branches being populated."""
    questions = [
        ClarificationQuestion(
            topic="grain",
            question="What should one row represent?",
            why="The requested analysis grain is unclear.",
        )
    ]
    output = ModelerOutput(
        design=design if include_design else None,
        questions=questions if include_design else [],
    )

    with pytest.raises(ValueError, match="either a design or clarification questions"):
        run_modeler(output)


@pytest.mark.parametrize("invalid_reference", ["key", "relationship", "metric", "card"])
def test_rejects_unknown_references(
    design: DataDesign,
    invalid_reference: str,
) -> None:
    """Reject references to tables or metrics absent from the design."""
    if invalid_reference == "key":
        design.keys[0].table = "missing_table"
    elif invalid_reference == "relationship":
        design.relationships = [
            RelationshipDefinition(
                child_table="fct_orders",
                child_columns=["customer_id"],
                parent_table="missing_table",
                parent_columns=["customer_id"],
                cardinality="many_to_one",
                rationale="Test an unknown parent table.",
            )
        ]
    elif invalid_reference == "metric":
        design.metrics[0].fact_table = "missing_table"
    else:
        design.dashboard.cards[0].metric = "missing_metric"

    with pytest.raises(ValueError, match="unknown"):
        run_modeler(ModelerOutput(design=design))
