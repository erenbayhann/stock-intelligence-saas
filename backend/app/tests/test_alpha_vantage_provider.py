from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.providers.news.alpha_vantage import AlphaVantageNewsProvider


def _ok_response(feed: list[dict]) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"feed": feed}
    return response


def _throttled_response() -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "Information": "Thank you for using Alpha Vantage! ... rate limit (25 requests per day)"
    }
    return response


def test_batches_into_groups_of_20_and_skips_dotted_tickers():
    # Regression test for a real, live-confirmed API constraint: 21+ tickers
    # in one request fails with a generic "Invalid inputs" error, and tickers
    # containing "." (e.g. BRK.B) fail with an "Invalid ticker format" error —
    # neither is documented, both confirmed by hitting the real API.
    tickers = {f"T{i}": f"Ticker {i}" for i in range(25)}
    tickers["BRK.B"] = "Berkshire Hathaway"

    provider = AlphaVantageNewsProvider(api_key="fake-key", max_requests_per_call=5)
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.get.side_effect = [_ok_response([]), _ok_response([])]

    with patch("app.providers.news.alpha_vantage.httpx.Client", return_value=mock_client):
        provider.fetch_articles(datetime.now(timezone.utc), tickers=tickers)

    assert mock_client.get.call_count == 2  # 25 valid tickers (BRK.B skipped) -> 2 batches of <=20
    first_call_tickers = mock_client.get.call_args_list[0].kwargs["params"]["tickers"].split(",")
    assert "BRK.B" not in first_call_tickers
    assert len(first_call_tickers) == 20


def test_rate_limited_response_sets_flag_and_returns_no_articles():
    provider = AlphaVantageNewsProvider(api_key="fake-key")
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.get.return_value = _throttled_response()

    with patch("app.providers.news.alpha_vantage.httpx.Client", return_value=mock_client):
        articles = provider.fetch_articles(datetime.now(timezone.utc), tickers={"AAPL": "Apple Inc."})

    assert articles == []
    assert provider.last_rate_limited is True


def test_matched_tickers_come_from_provider_relevance_not_headline_substring():
    feed = [
        {
            "title": "Tech giants report earnings",
            "url": "https://x.com/a",
            "time_published": "20260912T093000",
            "ticker_sentiment": [
                {"ticker": "AAPL", "relevance_score": "0.9"},
                {"ticker": "MSFT", "relevance_score": "0.4"},
                {"ticker": "UNREQUESTED", "relevance_score": "0.9"},
            ],
        }
    ]
    provider = AlphaVantageNewsProvider(api_key="fake-key")
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.get.return_value = _ok_response(feed)

    with patch("app.providers.news.alpha_vantage.httpx.Client", return_value=mock_client):
        articles = provider.fetch_articles(
            datetime.now(timezone.utc), tickers={"AAPL": "Apple Inc.", "MSFT": "Microsoft"}
        )

    assert len(articles) == 1
    # UNREQUESTED wasn't part of this call's ticker batch, so it's excluded
    # even though the provider's own payload flagged it as relevant.
    assert set(articles[0].matched_tickers) == {"AAPL", "MSFT"}
    assert articles[0].published_time == datetime(2026, 9, 12, 9, 30, tzinfo=timezone.utc)
