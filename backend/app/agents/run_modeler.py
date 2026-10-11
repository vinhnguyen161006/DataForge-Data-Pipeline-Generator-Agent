from app.profiler.schemas import DataProfile, ColumnProfile, TableProfile
import asyncio
from pathlib import Path

from app.agents.llm import StructuredLLM
from app.agents.schemas import ModelerOutput
from app.core.config import get_api_settings

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

    prompt_path = Path(__file__).parent / "prompts" / "modeler.md"
    system = prompt_path.read_text(encoding="utf-8")

    request_text = (
        "Design an OULAD dashboard showing student outcomes by module "
        "and presentation, including a pass rate KPI. "
        "Ask clarification questions when business definitions are missing."
        "\nClarified business rules for this experiment: "
        "Each row represents exactly one student-module-presentation combination. "
        "The combination of id_student, code_module, and code_presentation is unique. "
        "A student may appear in multiple module-presentation combinations. "
        "Pass means final_result is either Pass or Distinction. "
        "Pass rate equals the number of Pass or Distinction records divided "
        "by all student-module-presentation records in the selected group, "
        "including Fail and Withdrawn in the denominator."
    )

    prompt = (
        f"Analysis request:\n{request_text}\n\n"
        f"Statistical profile:\n{profile.model_dump_json(indent=2)}"
    )

    output = await llm.generate(
        system=system,
        prompt=prompt,
        schema=ModelerOutput,
    )

    print(output.model_dump_json(indent=2))
    print(llm.usage)


if __name__ == "__main__":
    asyncio.run(main())