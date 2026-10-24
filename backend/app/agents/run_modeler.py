import asyncio
from pathlib import Path

from app.agents.llm import StructuredLLM
from app.agents.modeler import propose_design
from app.core.config import get_api_settings
from app.profiler.schemas import DataProfile

profile_path = (
    Path(__file__).resolve().parents[3]
    / "eval"
    / "golden"
    / "tpch_sf1"
    / "metadata"
    / "modeler_profile.json"
)
profile = DataProfile.model_validate_json(profile_path.read_text(encoding="utf-8"))


async def main() -> None:
    settings = get_api_settings()

    llm = StructuredLLM(
        api_key=settings.gemini_api_key.get_secret_value(),
        model=settings.gemini_model,
    )

    request_text = (
        "Design a TPC-H sales dashboard showing revenue and order counts "
        "over time, by customer nation and product type. "
        "The business grain, revenue formula, reporting date, and treatment "
        "of returned items and order statuses are not yet confirmed. "
        "Ask clarification questions before making these business decisions."
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

    output_dir = profile_path.parents[1] / "modeler_results"
    await asyncio.to_thread(output_dir.mkdir, parents=True, exist_ok=True)

    for filename, output in [
        ("first_response.json", first_output),
        ("after_clarification.json", second_output),
    ]:
        await asyncio.to_thread(
            (output_dir / filename).write_text,
            output.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )

    print(f"Saved responses to: {output_dir}")

    if second_output.questions:
        print("Further clarification is required; review the remaining questions.")
    else:
        print("Design returned and reference validation passed.")

    print("\nToken usage:")
    print(llm.usage)


if __name__ == "__main__":
    asyncio.run(main())
