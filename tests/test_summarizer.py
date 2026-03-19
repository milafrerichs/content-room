from unittest.mock import patch

import pytest
from pydantic_ai.models.openai import OpenAIModel

from content_agent.summarizer import _get_model_spec


def test_get_model_spec_anthropic():
    result = _get_model_spec("anthropic", "claude-haiku-4-5")
    assert result == "anthropic:claude-haiku-4-5"


def test_get_model_spec_ollama():
    result = _get_model_spec("ollama", "llama3.2")
    assert isinstance(result, OpenAIModel)


def test_get_model_spec_openrouter():
    with patch("content_agent.summarizer.OpenRouterProvider"):
        result = _get_model_spec("openrouter", "anthropic/claude-haiku-4-5")
    assert isinstance(result, OpenAIModel)


def test_get_model_spec_invalid_provider():
    with pytest.raises(ValueError, match="Unsupported provider"):
        _get_model_spec("invalid", "some-model")
