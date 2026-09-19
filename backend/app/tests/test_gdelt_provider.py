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


# Real requests are paced 5s apart (see _MIN_REQUEST_INTERVAL_SECONDS) —
# patched out everywhere except the dedicated pacing test below, so the
# rest of the suite doesn't actually sleep.
@patch("app.providers.news.gdelt.time.sleep")
def test_one_failed_batch_does_not_discard_other_batches_articles(mock_sleep):
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


@patch("app.providers.news.gdelt.time.sleep")
def test_all_batches_failing_raises(mock_sleep):
    provider = GDELTNewsProvider(batch_size=1)
    tickers = {"AAPL": "Apple Inc."}

    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.get.side_effect = RuntimeError("down")

    with patch("app.providers.news.gdelt.httpx.Client", return_value=mock_client):
        with pytest.raises(Exception):
            provider.fetch_articles(datetime.now(timezone.utc), tickers=tickers)


@patch("app.providers.news.gdelt.time.sleep")
def test_wait_for_rate_limit_sleeps_for_the_remaining_gap(mock_sleep):
    # Regression for a real production issue: firing all ~13 per-ticker
    # batches back to back (no gap) got most of them 429'd by GDELT's real
    # "one request per 5 seconds" limit (verified live), starving out real
    # GDELT coverage in favor of whatever other provider has no such limit.
    # Exercises _wait_for_rate_limit directly (not through fetch_articles)
    # so this doesn't also mock tenacity's own internal time.monotonic() use.
    provider = GDELTNewsProvider()

    provider._wait_for_rate_limit()  # first call ever: nothing to wait for
    mock_sleep.assert_not_called()

    provider._wait_for_rate_limit()  # immediately after: must wait ~5s
    mock_sleep.assert_called_once()
    (waited,) = mock_sleep.call_args[0]
    assert 0 < waited <= 5.0


def _mock_client(*responses_or_errors):
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.get.side_effect = list(responses_or_errors)
    return client


@patch("app.providers.news.gdelt.time.sleep")
def test_run_is_abandoned_after_consecutive_batch_failures(mock_sleep):
    provider = GDELTNewsProvider(batch_size=1)
    tickers = {t: f"{t} Holdings" for t in ["AAAA", "BBBB", "CCCC", "DDDD", "EEEE"]}
    client = _mock_client(*[RuntimeError("dropped")] * 5)

    with patch("app.providers.news.gdelt.httpx.Client", return_value=client):
        with pytest.raises(Exception):
            provider.fetch_articles(datetime.now(timezone.utc), tickers=tickers)

    assert client.get.call_count == 3  # stopped hammering after 3 failures in a row
    assert set(provider.last_failed_tickers) == set(tickers)  # ...and the gap is reported, not lost


@patch("app.providers.news.gdelt.time.sleep")
def test_a_success_resets_the_consecutive_failure_count(mock_sleep):
    provider = GDELTNewsProvider(batch_size=1)
    tickers = {t: f"{t} Holdings" for t in ["AAAA", "BBBB", "CCCC", "DDDD", "EEEE"]}
    article = {"title": "AAAA Holdings up", "url": "https://x.com/a", "seendate": "20260910T120000Z"}
    client = _mock_client(
        RuntimeError("x"), RuntimeError("x"), _ok_response([article]), RuntimeError("x"), RuntimeError("x"),
    )

    with patch("app.providers.news.gdelt.httpx.Client", return_value=client):
        articles = provider.fetch_articles(datetime.now(timezone.utc), tickers=tickers)

    assert client.get.call_count == 5  # never 3 in a row, so every batch was still attempted
    assert len(articles) == 1


@patch("app.providers.news.gdelt.time.sleep")
def test_a_rejected_query_is_not_retried_and_does_not_trip_the_breaker(mock_sleep):
    provider = GDELTNewsProvider(batch_size=1)
    tickers = {t: f"{t} Holdings" for t in ["AAAA", "BBBB", "CCCC", "DDDD"]}
    rejected = MagicMock(status_code=200, text="The specified phrase is too short.\n")
    rejected.raise_for_status.return_value = None
    ok = _ok_response([{"title": "DDDD Holdings up", "url": "https://x.com/d", "seendate": "20260910T120000Z"}])
    client = _mock_client(rejected, rejected, rejected, ok)

    with patch("app.providers.news.gdelt.httpx.Client", return_value=client):
        articles = provider.fetch_articles(datetime.now(timezone.utc), tickers=tickers)

    assert client.get.call_count == 4  # one attempt each — no retries of a query that can never work
    assert len(articles) == 1  # 3 rejected batches in a row did NOT abandon the run


@patch("app.providers.news.gdelt.time.sleep")
def test_phrases_below_gdelts_minimum_length_are_left_out_of_the_query(mock_sleep):
    provider = GDELTNewsProvider()
    client = _mock_client(_ok_response([]))

    with patch("app.providers.news.gdelt.httpx.Client", return_value=client):
        provider.fetch_articles(
            datetime.now(timezone.utc), tickers={"UBER": "Uber", "AAPL": "Apple Inc.", "IBM": "IBM"}
        )

    query = client.get.call_args.kwargs["params"]["query"]
    assert '"Apple Inc."' in query
    assert "Uber" not in query and "IBM" not in query


@patch("app.providers.news.gdelt.time.sleep")
def test_a_batch_of_only_too_short_phrases_makes_no_request(mock_sleep):
    provider = GDELTNewsProvider()
    client = _mock_client()

    with patch("app.providers.news.gdelt.httpx.Client", return_value=client):
        articles = provider.fetch_articles(datetime.now(timezone.utc), tickers={"IBM": "IBM"})

    assert articles == []
    client.get.assert_not_called()
