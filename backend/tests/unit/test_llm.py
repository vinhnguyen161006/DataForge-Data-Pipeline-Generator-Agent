from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import BaseModel, Field, ValidationError

from app.agents.llm import StructuredLLM


class TableDesign(BaseModel):
    name: str = Field(min_length=1)
    grain: str = Field(min_length=1)


def make_response(
    text: str | None,
    prompt_tokens: int | None = 10,
    output_tokens: int | None = 5,
) -> SimpleNamespace:
    return SimpleNamespace(
        text=text,
        usage_metadata=SimpleNamespace(
            prompt_token_count=prompt_tokens,
            candidates_token_count=output_tokens,
        ),
    )


@pytest.fixture
def mock_generate() -> Iterator[AsyncMock]:
    generate = AsyncMock()

    client = MagicMock()
    client.models.generate_content = generate

    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=client)
    context.__aexit__ = AsyncMock(return_value=False)

    with patch("app.agents.llm.genai.Client") as factory:
        factory.return_value.aio = context
        yield generate


def make_llm() -> StructuredLLM:
    return StructuredLLM(
        api_key="fake-api-key",
        model="test-model",
        max_validation_retries=2,
    )


async def test_generate_returns_validated_output(mock_generate: AsyncMock) -> None:
    mock_generate.return_value = make_response('{"name":"fact_orders","grain":"One row per order"}')
    llm = make_llm()

    result = await llm.generate(
        system="Design warehouse tables.",
        prompt="Design an orders table.",
        schema=TableDesign,
    )

    assert isinstance(result, TableDesign)
    assert result.name == "fact_orders"
    assert result.grain == "One row per order"
    mock_generate.assert_awaited_once()
    assert llm.usage.calls == 1
    assert llm.usage.prompt_tokens == 10
    assert llm.usage.output_tokens == 5

    call = mock_generate.await_args
    assert call is not None
    arguments = call.kwargs
    assert arguments["model"] == "test-model"
    assert arguments["contents"] == "Design an orders table."

    config = arguments["config"]
    assert config.system_instruction == "Design warehouse tables."
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == TableDesign.model_json_schema()

    assert len(llm.usage.history) == 1
    entry = llm.usage.history[0]
    assert entry.model == "test-model"
    assert entry.prompt_tokens == 10
    assert entry.output_tokens == 5
    assert entry.validation_passed is True


@pytest.mark.parametrize(
    "invalid_text",
    [
        '{"name":"fact_orders"}',
        '{"name":"","grain":"One row per order"}',
        "This is not JSON.",
        None,
    ],
)
async def test_generate_retries_invalid_output(
    mock_generate: AsyncMock,
    invalid_text: str | None,
) -> None:
    mock_generate.side_effect = [
        make_response(invalid_text, prompt_tokens=10, output_tokens=5),
        make_response(
            '{"name":"fact_orders","grain":"One row per order"}',
            prompt_tokens=20,
            output_tokens=8,
        ),
    ]
    llm = make_llm()

    result = await llm.generate(
        system="Design warehouse tables.",
        prompt="Design an orders table.",
        schema=TableDesign,
    )

    assert result.name == "fact_orders"
    assert mock_generate.await_count == 2
    assert llm.usage.calls == 2
    assert llm.usage.prompt_tokens == 30
    assert llm.usage.output_tokens == 13

    retry_prompt = mock_generate.await_args_list[1].kwargs["contents"]
    assert "Design an orders table." in retry_prompt
    assert "Validation errors:" in retry_prompt

    assert len(llm.usage.history) == 2

    first, second = llm.usage.history
    assert first.prompt_tokens == 10
    assert first.output_tokens == 5
    assert first.validation_passed is False

    assert second.prompt_tokens == 20
    assert second.output_tokens == 8
    assert second.validation_passed is True


async def test_generate_stops_after_retry_limit(mock_generate: AsyncMock) -> None:
    mock_generate.return_value = make_response('{"name":"fact_orders"}')
    llm = make_llm()

    with pytest.raises(ValidationError):
        await llm.generate(
            system="Design warehouse tables.",
            prompt="Design an orders table.",
            schema=TableDesign,
        )

    assert mock_generate.await_count == 3
    assert llm.usage.calls == 3
    assert llm.usage.prompt_tokens == 30
    assert llm.usage.output_tokens == 15
    assert len(llm.usage.history) == 3
    assert all(not entry.validation_passed for entry in llm.usage.history)


async def test_generate_handles_missing_usage(mock_generate: AsyncMock) -> None:
    mock_generate.return_value = SimpleNamespace(
        text='{"name":"fact_orders","grain":"One row per order"}',
        usage_metadata=None,
    )
    llm = make_llm()

    result = await llm.generate(
        system="Design warehouse tables.",
        prompt="Design an orders table.",
        schema=TableDesign,
    )

    assert result.name == "fact_orders"
    assert llm.usage.calls == 1
    assert llm.usage.prompt_tokens == 0
    assert llm.usage.output_tokens == 0
    assert len(llm.usage.history) == 1
    assert llm.usage.history[0].prompt_tokens is None
    assert llm.usage.history[0].output_tokens is None
    assert llm.usage.history[0].validation_passed is True


async def test_generate_handles_missing_token_counts(
    mock_generate: AsyncMock,
) -> None:
    mock_generate.return_value = make_response(
        '{"name":"fact_orders","grain":"One row per order"}',
        prompt_tokens=None,
        output_tokens=None,
    )
    llm = make_llm()

    await llm.generate(
        system="Design warehouse tables.",
        prompt="Design an orders table.",
        schema=TableDesign,
    )

    assert llm.usage.prompt_tokens == 0
    assert llm.usage.output_tokens == 0


async def test_generate_propagates_api_errors(mock_generate: AsyncMock) -> None:
    mock_generate.side_effect = RuntimeError("API request failed")
    llm = make_llm()

    with pytest.raises(RuntimeError, match="API request failed"):
        await llm.generate(
            system="Design warehouse tables.",
            prompt="Design an orders table.",
            schema=TableDesign,
        )

    mock_generate.assert_awaited_once()
    assert llm.usage.calls == 1
    assert llm.usage.prompt_tokens == 0
    assert llm.usage.output_tokens == 0
