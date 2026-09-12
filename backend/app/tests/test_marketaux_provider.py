from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.providers.news.marketaux import MarketauxNewsProvider


def _page_response(articles: list[dict]) -> MagicMock:
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"data": articles}
    return response


def _article(uuid: str) -> dict:
    return {
        "uuid": uuid,
        "title": f"Headline {uuid}",
        "url": f"https://x.com/{uuid}",
        "published_at": "2026-09-12T10:00:00.000000Z",
    }


def test_paginates_past_the_free_tiers_3_article_per_response_cap():
    # Regression test: the free plan silently caps every response at 3
    # articles regardless of the requested `limit` (confirmed live against
    # the real API — limit=50 still returned exactly 3), but `page` returns
    # genuinely distinct articles, so pagination is how more of the 100
    # requests/day budget actually turns into more articles per call.
    provider = MarketauxNewsProvider(api_key="fake-key", max_pages_per_call=4)
    mock_client = MagicMock()
    mock_client.__enter__.return_value = mock_client
    mock_client.__exit__.return_value = False
    mock_client.get.side_effect = [
        _page_response([_article("a1"), _article("a2"), _article("a3")]),
        _page_response([_article("b1"), _article("b2"), _article("b3")]),
        _page_response([]),  # no more results -> stop paginating early
    ]

    with patch("app.providers.news.marketaux.httpx.Client", return_value=mock_client):
        articles = provider.fetch_articles(datetime.now(timezone.utc))

    assert len(articles) == 6
    assert mock_client.get.call_count == 3  # stopped after the empty page, never reached max_pages_per_call=4
    assert mock_client.get.call_args_list[1].kwargs["params"]["page"] == 2
