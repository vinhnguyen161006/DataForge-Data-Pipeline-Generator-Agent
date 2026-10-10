from dataclasses import dataclass, field
from typing import TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


@dataclass
class TokenCall:
    model: str
    prompt_tokens: int | None
    output_tokens: int | None
    validation_passed: bool


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    history: list[TokenCall] = field(default_factory=list)


@dataclass
class StructuredLLM:
    api_key: str
    model: str
    max_validation_retries: int = 2
    usage: TokenUsage = field(default_factory=TokenUsage)

    async def generate(self, *, system: str, prompt: str, schema: type[T]) -> T:
        """Generate validated JSON with bounded retries and token accounting."""
        if self.max_validation_retries < 0:
            raise ValueError("max_validation_retries must be non-negative.")

        current_prompt = prompt

        async with genai.Client(api_key=self.api_key).aio as client:
            for attempt in range(self.max_validation_retries + 1):
                self.usage.calls += 1

                response = await client.models.generate_content(
                    model=self.model,
                    contents=current_prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        response_mime_type="application/json",
                        response_json_schema=schema.model_json_schema(),
                        automatic_function_calling=types.AutomaticFunctionCallingConfig(
                            disable=True
                        ),
                    ),
                )

                metadata = response.usage_metadata

                prompt_tokens = metadata.prompt_token_count if metadata is not None else None
                output_tokens = metadata.candidates_token_count if metadata is not None else None

                self.usage.prompt_tokens += prompt_tokens or 0
                self.usage.output_tokens += output_tokens or 0

                call_usage = TokenCall(
                    model=self.model,
                    prompt_tokens=prompt_tokens,
                    output_tokens=output_tokens,
                    validation_passed=False,
                )
                self.usage.history.append(call_usage)

                try:
                    result = schema.model_validate_json(response.text or "")
                except ValidationError as error:
                    if attempt == self.max_validation_retries:
                        raise

                    validation_errors = error.json(
                        include_input=False,
                        include_url=False,
                    )
                    current_prompt = (
                        f"{prompt}\n\n"
                        "Your previous response failed schema validation.\n"
                        f"Validation errors: {validation_errors}\n"
                        "Return a corrected JSON response matching the schema."
                    )
                else:
                    call_usage.validation_passed = True
                    return result

        raise RuntimeError("No generation attempt was made.")
