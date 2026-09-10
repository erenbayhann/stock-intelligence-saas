from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.providers.news.gdelt import GDELTNewsProvider


def _ok_response(articles: list[dict]) -> MagicMock:
    response = MagicMock()
    response.status_code = 200
    response.text = '{"articles": []}'  # non-empty, starts with "{"
    response.json.return_value = {"articles": articles}
    response.raise_for_status.return_value = None
    return response


def test_one_failed_batch_does_not_discard_other_batches_articles():
    # Regression test for a real bug found via live testing: a batch that
    # exhausts retries used to raise out of fetch_articles() entirely,
    # silently discarding articles already fetched from earlier successful
    # batches in the same call.
    provider = GDELTNewsProvider(batch_size=1)
    tickers = {"AAPL": "Apple Inc.", "MSFT": "Microsoft"}

    good_response = _ok_response(
        [{"title": "Apple Inc. hits new high", "url": "https://x.com/a", "seendate": "20260910T120000Z"}]
    )

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    # First batch (AAPL) succeeds; second batch (MSFT) fails outright (a
    # non-rate-limit exception bypasses tenacity's retry filter immediately).
    mock_client.get.side_effect = [good_response, RuntimeError("connection reset")]

    with patch("app.providers.news.gdelt.httpx.Client", return_value=mock_client):
        articles = provider.fetch_articles(datetime.now(timezone.utc), tickers=tickers)

    assert len(articles) == 1
    assert articles[0].url == "https://x.com/a"
    assert articles[0].matched_tickers == ("AAPL",)
    assert provider.last_failed_tickers == ["MSFT"]


def test_all_batches_failing_raises():
    provider = GDELTNewsProvider(batch_size=1)
    tickers = {"AAPL": "Apple Inc."}

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.get.side_effect = RuntimeError("down")

    with patch("app.providers.news.gdelt.httpx.Client", return_value=mock_client):
        with pytest.raises(Exception):
            provider.fetch_articles(datetime.now(timezone.utc), tickers=tickers)
