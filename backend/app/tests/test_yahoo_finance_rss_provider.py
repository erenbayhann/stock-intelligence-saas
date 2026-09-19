from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.providers.news.yahoo_finance_rss import YahooFinanceRSSError, YahooFinanceRSSProvider

SINCE = datetime(2026, 9, 18, 0, 0, tzinfo=timezone.utc)


def _feed(*items: tuple[str, str, str, str]) -> MagicMock:
    """items: (title, link, guid, pubDate)"""
    body = "".join(
        f"<item><title>{t}</title><link>{link}</link><guid isPermaLink=\"false\">{g}</guid>"
        f"<pubDate>{d}</pubDate><description>ignored summary text</description></item>"
        for t, link, g, d in items
    )
    response = MagicMock()
    response.content = f'<?xml version="1.0"?><rss version="2.0"><channel>{body}</channel></rss>'.encode()
    response.raise_for_status.return_value = None
    return response


def _client(*side_effect):
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.get.side_effect = list(side_effect)
    return client


def _fetch(provider, client, tickers):
    with patch("app.providers.news.yahoo_finance_rss.httpx.Client", return_value=client) as ctor, patch(
        "app.providers.news.yahoo_finance_rss.time.sleep"
    ):
        articles = provider.fetch_articles(SINCE, tickers=tickers)
    return articles, ctor


def test_parses_headlines_and_keeps_only_what_is_needed():
    client = _client(_feed(("Apple soars", "https://y/a", "g-1", "Fri, 18 Sep 2026 14:30:00 +0000")))

    articles, _ = _fetch(YahooFinanceRSSProvider(), client, {"AAPL": "Apple Inc."})

    assert len(articles) == 1
    article = articles[0]
    assert (article.source, article.title, article.url) == ("yahoo_finance", "Apple soars", "https://y/a")
    assert article.source_article_id == "g-1"
    assert article.published_time == datetime(2026, 9, 18, 14, 30, tzinfo=timezone.utc)
    assert article.matched_tickers == ("AAPL",)
    assert "ignored summary text" not in str(article.raw_payload)  # feed description is never kept


def test_sends_an_honest_user_agent():
    client = _client(_feed())
    _, ctor = _fetch(YahooFinanceRSSProvider(), client, {"AAPL": "Apple Inc."})
    assert "StockHyperion" in ctor.call_args.kwargs["headers"]["User-Agent"]


def test_dotted_tickers_use_yahoos_dashed_symbol():
    client = _client(_feed())
    _fetch(YahooFinanceRSSProvider(), client, {"BRK.B": "Berkshire Hathaway"})
    assert client.get.call_args.kwargs["params"]["s"] == "BRK-B"


def test_a_story_in_several_feeds_becomes_one_article_linked_to_every_ticker():
    same = ("Chip stocks rally", "https://y/chips", "g-9", "Fri, 18 Sep 2026 15:00:00 +0000")
    client = _client(_feed(same), _feed(same))

    articles, _ = _fetch(YahooFinanceRSSProvider(), client, {"NVDA": "Nvidia", "AMD": "Advanced Micro Devices"})

    assert len(articles) == 1
    assert articles[0].matched_tickers == ("NVDA", "AMD")


def test_old_headlines_and_unparsable_dates_are_dropped_never_given_the_fetch_time():
    client = _client(_feed(
        ("Too old", "https://y/old", "g-1", "Thu, 17 Sep 2026 23:59:00 +0000"),
        ("No usable date", "https://y/bad", "g-2", "not a date"),
        ("Fresh", "https://y/new", "g-3", "Fri, 18 Sep 2026 09:00:00 +0000"),
    ))

    articles, _ = _fetch(YahooFinanceRSSProvider(), client, {"AAPL": "Apple Inc."})

    assert [a.title for a in articles] == ["Fresh"]


def test_only_the_newest_n_headlines_per_ticker_are_kept():
    client = _client(_feed(
        ("h1", "https://y/1", "1", "Fri, 18 Sep 2026 10:00:00 +0000"),
        ("h3", "https://y/3", "3", "Fri, 18 Sep 2026 12:00:00 +0000"),
        ("h2", "https://y/2", "2", "Fri, 18 Sep 2026 11:00:00 +0000"),
    ))

    articles, _ = _fetch(YahooFinanceRSSProvider(items_per_ticker=2), client, {"AAPL": "Apple Inc."})

    assert sorted(a.title for a in articles) == ["h2", "h3"]


def test_one_failing_feed_does_not_discard_the_others():
    client = _client(httpx.ConnectError("boom"), _feed(("Fine", "https://y/f", "g", "Fri, 18 Sep 2026 10:00:00 +0000")))
    provider = YahooFinanceRSSProvider()

    articles, _ = _fetch(provider, client, {"AAPL": "Apple Inc.", "MSFT": "Microsoft"})

    assert [a.title for a in articles] == ["Fine"]
    assert provider.last_failed_tickers == ["AAPL"]


def test_run_is_abandoned_after_consecutive_failures_and_raises_when_nothing_came_back():
    tickers = {t: t for t in ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG"]}
    client = _client(*[httpx.ConnectError("down")] * 7)
    provider = YahooFinanceRSSProvider()

    with pytest.raises(YahooFinanceRSSError):
        _fetch(provider, client, tickers)

    assert client.get.call_count == 5
    assert set(provider.last_failed_tickers) == set(tickers)  # unattempted ones are reported too
