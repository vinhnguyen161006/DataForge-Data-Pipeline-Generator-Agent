from dataclasses import dataclass, field
from typing import TypeVar
from google import genai
from google.genai import types
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0


@dataclass
class StructuredLLM:
    api_key: str
    model: str
    max_validation_retries: int = 2
    usage: TokenUsage = field(default_factory=TokenUsage)

    async def generate(self, *, system: str, prompt: str, schema: type[T]) -> T:
        async with genai.Client(api_key=self.api_key).aio as client:
            self.usage.calls += 1
            response = await client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    response_mime_type="application/json",
                    response_json_schema=schema.model_json_schema(),
                ),
            )

            if response.usage_metadata is not None:
                self.usage.prompt_tokens += (
                    response.usage_metadata.prompt_token_count or 0
                )
                self.usage.output_tokens += (
                    response.usage_metadata.candidates_token_count or 0
                )

            return schema.model_validate_json(response.text or "")