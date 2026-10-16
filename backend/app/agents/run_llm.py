import asyncio

from pydantic import BaseModel, Field

from app.agents.llm import StructuredLLM
from app.core.config import get_api_settings


class TableDesign(BaseModel):
    name: str = Field(min_length=1)
    grain: str = Field(min_length=1)


async def main() -> None:
    settings = get_api_settings()

    llm = StructuredLLM(
        api_key=settings.gemini_api_key.get_secret_value(),
        model=settings.gemini_model,
    )

    result = await llm.generate(
        system="You design data warehouse tables.",
        prompt=(
            "Suggest a fact table for orders. "
            "Each row represents one order. Return its name and grain."
        ),
        schema=TableDesign,
    )

    print(result)
    print(type(result))
    print(llm.usage)


if __name__ == "__main__":
    asyncio.run(main())
