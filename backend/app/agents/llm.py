from dataclasses import dataclass, field
from typing import TypeVar

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
        """TODO: call Gemini (google-genai) with response_json_schema=schema.model_json_schema().

        Validate with schema.model_validate_json; on ValidationError retry up to
        max_validation_retries with the error appended; record token usage.
        """
        raise NotImplementedError
