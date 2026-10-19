import asyncio

from app.agents.llm import StructuredLLM
from app.agents.modeler import propose_design
from app.core.config import get_api_settings
from app.profiler.schemas import ColumnProfile, DataProfile, TableProfile

profile = DataProfile(
    tables=[
        TableProfile(
            name="studentInfo",
            source_file="studentInfo.csv",
            row_count=4,
            columns=[
                ColumnProfile(
                    name="id_student",
                    inferred_type="integer",
                    row_count=4,
                    null_ratio=0.0,
                    distinct_count=3,
                ),
                ColumnProfile(
                    name="code_module",
                    inferred_type="string",
                    row_count=4,
                    null_ratio=0.0,
                    distinct_count=2,
                ),
                ColumnProfile(
                    name="code_presentation",
                    inferred_type="string",
                    row_count=4,
                    null_ratio=0.0,
                    distinct_count=1,
                ),
                ColumnProfile(
                    name="final_result",
                    inferred_type="string",
                    row_count=4,
                    null_ratio=0.0,
                    distinct_count=3,
                ),
            ],
        )
    ],
    key_candidates=[],
    relationship_candidates=[],
    notes=[
        "Synthetic OULAD profile for a prompt spike; counts are illustrative.",
    ],
)


async def main() -> None:
    settings = get_api_settings()

    llm = StructuredLLM(
        api_key=settings.gemini_api_key.get_secret_value(),
        model=settings.gemini_model,
    )

    request_text = (
        "Design an OULAD dashboard showing student outcomes by module "
        "and presentation, including a pass rate KPI. "
        "The business grain and the definition of pass rate are not yet confirmed."
    )

    first_output = await propose_design(
        llm,
        request_text=request_text,
        profile=profile,
        answers=[],
    )

    print("=== First response: clarification expected ===")
    print(first_output.model_dump_json(indent=2))

    if first_output.design is not None:
        raise ValueError("Expected clarification before designing with unconfirmed business rules.")

    answers: list[dict[str, str]] = []

    for question in first_output.questions:
        print(f"\nTopic: {question.topic}")
        print(f"Question: {question.question}")
        print(f"Why: {question.why}")

        if question.options:
            print("Options:", question.options)

        answer = await asyncio.to_thread(input, "Your answer: ")
        if not answer.strip():
            raise ValueError("A clarification answer must not be empty.")

        answers.append(
            {
                "question": question.question,
                "answer": answer.strip(),
            }
        )

    second_output = await propose_design(
        llm,
        request_text=request_text,
        profile=profile,
        answers=answers,
    )

    print("\n=== Response after clarification ===")
    print(second_output.model_dump_json(indent=2))

    if second_output.questions:
        print("Further clarification is required; review the remaining questions.")
    else:
        print("Design returned and reference validation passed.")

    print("\nToken usage:")
    print(llm.usage)


if __name__ == "__main__":
    asyncio.run(main())
