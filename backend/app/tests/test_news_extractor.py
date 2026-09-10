import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import pytest

from app.providers.llm.news_extractor import ClaudeNewsExtractor, LLMProviderError


def _fake_response(payload: dict, tokens_in: int = 10, tokens_out: int = 5):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps(payload))],
        usage=SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out),
    )


def _extractor() -> ClaudeNewsExtractor:
    return ClaudeNewsExtractor(api_key="sk-ant-test-not-real")


def test_extract_clamps_out_of_range_values():
    # Regression test: Anthropic's structured-output schema doesn't support
    # minimum/maximum on "number" properties (confirmed via a real 400), so
    # out-of-range model output must be clamped in code, not rejected by the API.
    extractor = _extractor()
    extractor._client.messages.create = MagicMock(
        return_value=_fake_response({"sentiment": 1.7, "event_category": "Earnings", "importance": -0.3})
    )

    result = extractor.extract(title="t", source="s", company_name="Apple", ticker="AAPL")

    assert result.sentiment == 1.0
    assert result.importance == 0.0
    assert result.event_category == "Earnings"
    assert result.tokens_in == 10
    assert result.tokens_out == 5


def test_extract_passes_through_in_range_values():
    extractor = _extractor()
    extractor._client.messages.create = MagicMock(
        return_value=_fake_response({"sentiment": 0.42, "event_category": "Guidance", "importance": 0.9})
    )

    result = extractor.extract(title="t", source="s", company_name="Apple", ticker="AAPL")

    assert result.sentiment == 0.42
    assert result.importance == 0.9


def test_extract_wraps_rate_limit_error():
    extractor = _extractor()
    request = MagicMock()
    response = MagicMock(status_code=429, headers={})
    extractor._client.messages.create = MagicMock(
        side_effect=anthropic.RateLimitError("rate limited", response=response, body=None)
    )

    with pytest.raises(LLMProviderError) as exc_info:
        extractor.extract(title="t", source="s", company_name="Apple", ticker="AAPL")
    assert exc_info.value.kind == "rate_limited"


def test_extract_classifies_insufficient_credit():
    extractor = _extractor()
    response = MagicMock(status_code=402, headers={})
    body = {"type": "error", "error": {"type": "billing_error", "message": "credit balance too low"}}
    extractor._client.messages.create = MagicMock(
        side_effect=anthropic.APIStatusError("credit balance too low", response=response, body=body)
    )

    with pytest.raises(LLMProviderError) as exc_info:
        extractor.extract(title="t", source="s", company_name="Apple", ticker="AAPL")
    assert exc_info.value.kind == "insufficient_credit"


def test_extract_classifies_other_status_errors_as_provider_error():
    extractor = _extractor()
    response = MagicMock(status_code=500, headers={})
    extractor._client.messages.create = MagicMock(
        side_effect=anthropic.InternalServerError("boom", response=response, body=None)
    )

    with pytest.raises(LLMProviderError) as exc_info:
        extractor.extract(title="t", source="s", company_name="Apple", ticker="AAPL")
    assert exc_info.value.kind == "provider_error"
