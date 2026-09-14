import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import anthropic
import pytest

from app.providers.llm.news_extractor import ClaudeNewsExtractor, LLMProviderError

_UNIVERSE = [
    ("AAPL", "Apple Inc.", "Information Technology"),
    ("XOM", "Exxon Mobil Corp.", "Energy"),
    ("CVX", "Chevron Corp.", "Energy"),
]


def _fake_response(payload: dict, tokens_in: int = 10, tokens_out: int = 5):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=json.dumps(payload))],
        usage=SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out),
    )


def _extractor() -> ClaudeNewsExtractor:
    return ClaudeNewsExtractor(api_key="sk-ant-test-not-real")


def test_classify_clamps_out_of_range_values():
    # Regression test: Anthropic's structured-output schema doesn't support
    # minimum/maximum on "number" properties (confirmed via a real 400), so
    # out-of-range model output must be clamped in code, not rejected by the API.
    extractor = _extractor()
    extractor._client.messages.create = MagicMock(
        return_value=_fake_response(
            {
                "relevant_tickers": [
                    {"ticker": "AAPL", "relevance": 1.7, "sentiment": 1.7, "event_category": "Earnings", "importance": -0.3}
                ]
            }
        )
    )

    result = extractor.classify(title="t", source="s", universe=_UNIVERSE)

    assert len(result.tickers) == 1
    assert result.tickers[0].relevance == 1.0
    assert result.tickers[0].sentiment == 1.0
    assert result.tickers[0].importance == 0.0
    assert result.tickers[0].event_category == "Earnings"
    assert result.tokens_in == 10
    assert result.tokens_out == 5


def test_classify_returns_multiple_tickers_with_independent_sentiment():
    # This is the whole point of the redesign: the same headline can be
    # relevant to several companies with genuinely different per-company
    # sentiment (e.g. a commodity price move helps producers, hurts heavy
    # consumers of that commodity) — a single article-level sentiment value
    # couldn't represent that.
    extractor = _extractor()
    extractor._client.messages.create = MagicMock(
        return_value=_fake_response(
            {
                "relevant_tickers": [
                    {"ticker": "XOM", "relevance": 0.9, "sentiment": 0.6, "event_category": "Macroeconomic exposure", "importance": 0.5},
                    {"ticker": "CVX", "relevance": 0.85, "sentiment": 0.5, "event_category": "Macroeconomic exposure", "importance": 0.5},
                ]
            }
        )
    )

    result = extractor.classify(title="Oil prices surge on OPEC+ supply cut", source="s", universe=_UNIVERSE)

    tickers = {t.ticker: t for t in result.tickers}
    assert set(tickers) == {"XOM", "CVX"}
    assert tickers["XOM"].sentiment == 0.6
    assert tickers["CVX"].sentiment == 0.5


def test_classify_drops_tickers_the_model_invented():
    # Never trust a ticker back from the model that wasn't in the universe
    # we gave it — the schema can't enforce this (it's a free-text string
    # property, not an enum, since the universe is dynamic).
    extractor = _extractor()
    extractor._client.messages.create = MagicMock(
        return_value=_fake_response(
            {
                "relevant_tickers": [
                    {"ticker": "AAPL", "relevance": 0.9, "sentiment": 0.5, "event_category": "Earnings", "importance": 0.5},
                    {"ticker": "NOTREAL", "relevance": 0.9, "sentiment": 0.5, "event_category": "Earnings", "importance": 0.5},
                ]
            }
        )
    )

    result = extractor.classify(title="t", source="s", universe=_UNIVERSE)

    assert [t.ticker for t in result.tickers] == ["AAPL"]


def test_classify_empty_relevant_tickers_is_valid():
    extractor = _extractor()
    extractor._client.messages.create = MagicMock(return_value=_fake_response({"relevant_tickers": []}))

    result = extractor.classify(title="Local weather report", source="s", universe=_UNIVERSE)

    assert result.tickers == ()


def test_classify_wraps_rate_limit_error():
    extractor = _extractor()
    response = MagicMock(status_code=429, headers={})
    extractor._client.messages.create = MagicMock(
        side_effect=anthropic.RateLimitError("rate limited", response=response, body=None)
    )

    with pytest.raises(LLMProviderError) as exc_info:
        extractor.classify(title="t", source="s", universe=_UNIVERSE)
    assert exc_info.value.kind == "rate_limited"


def test_classify_classifies_insufficient_credit():
    extractor = _extractor()
    response = MagicMock(status_code=402, headers={})
    body = {"type": "error", "error": {"type": "billing_error", "message": "credit balance too low"}}
    extractor._client.messages.create = MagicMock(
        side_effect=anthropic.APIStatusError("credit balance too low", response=response, body=body)
    )

    with pytest.raises(LLMProviderError) as exc_info:
        extractor.classify(title="t", source="s", universe=_UNIVERSE)
    assert exc_info.value.kind == "insufficient_credit"


def test_classify_classifies_other_status_errors_as_provider_error():
    extractor = _extractor()
    response = MagicMock(status_code=500, headers={})
    extractor._client.messages.create = MagicMock(
        side_effect=anthropic.InternalServerError("boom", response=response, body=None)
    )

    with pytest.raises(LLMProviderError) as exc_info:
        extractor.classify(title="t", source="s", universe=_UNIVERSE)
    assert exc_info.value.kind == "provider_error"
