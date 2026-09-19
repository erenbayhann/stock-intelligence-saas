from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db.session import get_db
from app.main import app
from app.models.market_price import MarketPrice
from app.models.news import NewsArticle, NewsCompanyLink
from app.models.news_pick import NewsPickResult, NewsPickRun
from app.models.security import Security
from app.services.news_pick_service import (
    TOP_N,
    NewsPicksAlreadyExistError,
    evaluate_pending_news_picks,
    generate_news_pick_run,
    get_latest_news_picks,
    get_news_pick_history,
    lock_moment,
    news_pick_performance,
)
from app.services.universe_service import seed_benchmarks, seed_universe

TICKERS = ["AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG"]
UNIVERSE = [
    {"ticker": t, "name": f"{t} Corp", "sector": "Test", "exchange": "NYSE", "cik": f"00000{i:02d}"}
    for i, t in enumerate(TICKERS)
]
TARGET = date(2026, 9, 18)  # a Friday
AS_OF = lock_moment(TARGET)  # 2026-09-18 13:15Z (09:15 EDT)
PRIOR_CLOSE = datetime(2026, 9, 17, 20, 0, tzinfo=timezone.utc)  # 16:00 EDT the day before


def _ids(db_session):
    return {s.ticker: s.id for s in db_session.scalars(select(Security))}


def _bar(security_id, day: date, close: float):
    return MarketPrice(
        security_id=security_id, ts=datetime(day.year, day.month, day.day, 4, tzinfo=timezone.utc),
        session_type="regular", open=close, high=close, low=close, close=close,
        volume=1_000_000, source="alpaca_iex",
    )


def _news(db_session, security_id, key, *, sentiment, importance, relevance=1.0,
          published=None, classified=None, duplicate_of=None):
    published = published or (AS_OF - timedelta(hours=3))
    article = NewsArticle(
        source="marketaux", title=f"Headline {key}", url=f"https://example.com/{key}",
        published_time=published, classified_at=classified or (published + timedelta(minutes=5)),
        is_duplicate_of=duplicate_of,
    )
    db_session.add(article)
    db_session.flush()
    db_session.add(NewsCompanyLink(
        news_article_id=article.id, security_id=security_id,
        sentiment=sentiment, importance=importance, relevance=relevance, event_category="Other",
    ))
    db_session.commit()
    return article


def _setup(db_session, with_prior_session=True):
    seed_universe(db_session, UNIVERSE)
    seed_benchmarks(db_session)
    ids = _ids(db_session)
    if with_prior_session:
        db_session.add(_bar(ids["SPY"], date(2026, 9, 17), 100.0))
        db_session.commit()
    return ids


def _generate(db_session, **kwargs):
    return generate_news_pick_run(db_session, set(TICKERS), TARGET, AS_OF, **kwargs)


def test_picks_rank_by_net_positive_score_and_skip_net_negative_stocks(db_session):
    ids = _setup(db_session)
    _news(db_session, ids["AAA"], "a1", sentiment=0.9, importance=0.8)   # 0.72
    _news(db_session, ids["AAA"], "a2", sentiment=0.5, importance=0.6)   # 0.30  -> 1.02
    _news(db_session, ids["BBB"], "b1", sentiment=1.0, importance=0.9)   # 0.90
    _news(db_session, ids["CCC"], "c1", sentiment=0.4, importance=0.5)   # +0.20
    _news(db_session, ids["CCC"], "c2", sentiment=-0.9, importance=0.9)  # -0.81 -> net -0.61
    _news(db_session, ids["DDD"], "d1", sentiment=-0.8, importance=0.7)  # -0.56

    result = _generate(db_session)

    assert [p["ticker"] for p in result["picks"]] == ["AAA", "BBB"]
    assert result["candidates_scored"] == 4  # every stock that had classified news
    latest = get_latest_news_picks(db_session)
    assert [p["rank"] for p in latest["picks"]] == [1, 2]
    assert latest["picks"][0]["news_score"] == pytest.approx(1.02)
    assert latest["picks"][0]["article_count"] == 2
    assert latest["picks"][0]["avg_sentiment"] == pytest.approx(0.7)


def test_only_top_five_are_kept(db_session):
    ids = _setup(db_session)
    for i, ticker in enumerate(TICKERS):  # 7 positive stocks, strictly decreasing score
        _news(db_session, ids[ticker], f"t{i}", sentiment=0.9 - i * 0.1, importance=0.9)

    result = _generate(db_session)

    assert len(result["picks"]) == TOP_N
    assert [p["ticker"] for p in result["picks"]] == TICKERS[:TOP_N]


def test_no_positive_news_still_records_an_honest_empty_run(db_session):
    ids = _setup(db_session)
    _news(db_session, ids["AAA"], "neg", sentiment=-0.5, importance=0.8)

    result = _generate(db_session)

    assert result["picks"] == []
    run = db_session.scalar(select(NewsPickRun))
    assert run.candidates_scored == 1


def test_selection_is_point_in_time_correct(db_session):
    ids = _setup(db_session)
    good = dict(sentiment=0.8, importance=0.8)
    _news(db_session, ids["AAA"], "in-window", **good, published=PRIOR_CLOSE + timedelta(minutes=1))
    _news(db_session, ids["BBB"], "before-prior-close", **good, published=PRIOR_CLOSE - timedelta(minutes=1))
    _news(db_session, ids["CCC"], "published-after-lock", **good, published=AS_OF + timedelta(minutes=1),
          classified=AS_OF + timedelta(minutes=6))
    _news(db_session, ids["DDD"], "classified-after-lock", **good, published=AS_OF - timedelta(hours=1),
          classified=AS_OF + timedelta(seconds=1))

    result = _generate(db_session)

    assert [p["ticker"] for p in result["picks"]] == ["AAA"]


def test_unclassified_duplicate_benchmark_and_non_universe_news_never_count(db_session):
    ids = _setup(db_session)
    original = _news(db_session, ids["AAA"], "orig", sentiment=0.6, importance=0.6)
    _news(db_session, ids["BBB"], "dup", sentiment=0.9, importance=0.9, duplicate_of=original.id)
    _news(db_session, ids["SPY"], "bench", sentiment=0.9, importance=0.9)  # benchmark, not in universe
    unclassified = NewsArticle(
        source="marketaux", title="raw", url="https://example.com/raw",
        published_time=AS_OF - timedelta(hours=2), classified_at=None,
    )
    db_session.add(unclassified)
    db_session.flush()
    db_session.add(NewsCompanyLink(news_article_id=unclassified.id, security_id=ids["CCC"], relevance=1.0))
    db_session.commit()

    result = _generate(db_session)

    assert [p["ticker"] for p in result["picks"]] == ["AAA"]


def test_window_falls_back_to_24_hours_without_a_prior_session_on_record(db_session):
    ids = _setup(db_session, with_prior_session=False)
    good = dict(sentiment=0.8, importance=0.8)
    _news(db_session, ids["AAA"], "23h", **good, published=AS_OF - timedelta(hours=23))
    _news(db_session, ids["BBB"], "25h", **good, published=AS_OF - timedelta(hours=25))

    result = _generate(db_session)

    assert [p["ticker"] for p in result["picks"]] == ["AAA"]


def test_evidence_is_the_top_positive_headlines_frozen_at_lock_time(db_session):
    ids = _setup(db_session)
    for i, sentiment in enumerate([0.3, 0.9, 0.6, 0.8]):
        _news(db_session, ids["AAA"], f"e{i}", sentiment=sentiment, importance=1.0)
    _news(db_session, ids["AAA"], "neg", sentiment=-0.2, importance=1.0)

    _generate(db_session)
    pick = get_latest_news_picks(db_session)["picks"][0]

    assert [e["title"] for e in pick["evidence"]] == ["Headline e1", "Headline e3", "Headline e2"]
    assert pick["positive_count"] == 4 and pick["negative_count"] == 1


def test_picks_for_a_session_are_generated_once(db_session):
    ids = _setup(db_session)
    _news(db_session, ids["AAA"], "a", sentiment=0.8, importance=0.8)
    _generate(db_session)

    with pytest.raises(NewsPicksAlreadyExistError):
        _generate(db_session)
    assert len(db_session.scalars(select(NewsPickRun)).all()) == 1


def test_run_written_long_after_its_cutoff_is_flagged_reconstructed(db_session):
    _setup(db_session)
    past_cutoff = datetime.now(timezone.utc) - timedelta(days=2)

    generate_news_pick_run(db_session, set(TICKERS), past_cutoff.date(), past_cutoff)

    assert get_latest_news_picks(db_session)["reconstructed"] is True


def test_live_run_is_not_flagged_reconstructed(db_session):
    _setup(db_session)
    now = datetime.now(timezone.utc)
    generate_news_pick_run(db_session, set(TICKERS), now.date(), now)

    assert get_latest_news_picks(db_session)["reconstructed"] is False


def test_results_are_written_once_after_the_session_closes(db_session):
    ids = _setup(db_session)
    for ticker, sentiment in [("AAA", 0.9), ("BBB", 0.8), ("CCC", 0.7)]:
        _news(db_session, ids[ticker], ticker, sentiment=sentiment, importance=1.0)
    _generate(db_session)
    # Prior close 100 everywhere; on the 18th: SPY +0.5%, AAA +2%, BBB -1%, CCC has no bar yet.
    for ticker in ["AAA", "BBB", "CCC"]:
        db_session.add(_bar(ids[ticker], date(2026, 9, 17), 100.0))
    db_session.add_all([
        _bar(ids["SPY"], date(2026, 9, 18), 100.5),
        _bar(ids["AAA"], date(2026, 9, 18), 102.0),
        _bar(ids["BBB"], date(2026, 9, 18), 99.0),
    ])
    db_session.commit()

    first = evaluate_pending_news_picks(db_session)
    second = evaluate_pending_news_picks(db_session)

    assert first == {"news_picks_evaluated": 2, "news_picks_not_yet_closed": 1}
    assert second == {"news_picks_evaluated": 0, "news_picks_not_yet_closed": 1}
    assert len(db_session.scalars(select(NewsPickResult)).all()) == 2

    picks = {p["ticker"]: p for p in get_latest_news_picks(db_session)["picks"]}
    assert picks["AAA"]["hit"] is True
    assert picks["AAA"]["actual_return"] == pytest.approx(0.02)
    assert picks["AAA"]["benchmark_return"] == pytest.approx(0.005)
    assert picks["AAA"]["excess_return"] == pytest.approx(0.015)
    assert picks["BBB"]["hit"] is False
    assert picks["CCC"]["hit"] is None and picks["CCC"]["actual_return"] is None  # still pending


def test_performance_counts_only_graded_picks_in_the_window(db_session):
    ids = _setup(db_session)
    for ticker, sentiment in [("AAA", 0.9), ("BBB", 0.8), ("CCC", 0.7)]:
        _news(db_session, ids[ticker], ticker, sentiment=sentiment, importance=1.0)
    _generate(db_session)
    for ticker in ["AAA", "BBB", "CCC"]:
        db_session.add(_bar(ids[ticker], date(2026, 9, 17), 100.0))
    db_session.add_all([
        _bar(ids["SPY"], date(2026, 9, 18), 100.5),
        _bar(ids["AAA"], date(2026, 9, 18), 102.0),
        _bar(ids["BBB"], date(2026, 9, 18), 99.0),
    ])
    db_session.commit()
    evaluate_pending_news_picks(db_session)

    perf = news_pick_performance(db_session, days=7, today=date(2026, 9, 19))

    assert perf["n_picks"] == 3 and perf["n_graded"] == 2 and perf["n_days"] == 1
    assert perf["hit_rate"] == pytest.approx(0.5)
    assert perf["mean_actual_return"] == pytest.approx(0.005)
    assert perf["mean_benchmark_return"] == pytest.approx(0.005)
    assert perf["mean_excess_return"] == pytest.approx(0.0)

    stale = news_pick_performance(db_session, days=7, today=date(2026, 10, 30))
    assert stale["n_picks"] == 0 and stale["hit_rate"] is None


def test_history_lists_most_recent_session_first(db_session):
    ids = _setup(db_session)
    _news(db_session, ids["AAA"], "a", sentiment=0.8, importance=0.8)
    _generate(db_session)
    generate_news_pick_run(db_session, set(TICKERS), date(2026, 9, 21), lock_moment(date(2026, 9, 21)))

    history = get_news_pick_history(db_session, limit=7)

    assert [h["target_session_date"] for h in history] == [date(2026, 9, 21), TARGET]


def _client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    return TestClient(app)


def test_latest_endpoint_404s_before_any_picks_exist(db_session):
    client = _client(db_session)
    try:
        response = client.get("/api/v1/news-picks/latest")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404


def test_endpoints_serve_locked_picks_with_their_evidence(db_session):
    ids = _setup(db_session)
    _news(db_session, ids["AAA"], "a", sentiment=0.8, importance=0.8)
    _generate(db_session)

    client = _client(db_session)
    try:
        latest = client.get("/api/v1/news-picks/latest")
        history = client.get("/api/v1/news-picks/history?limit=7")
    finally:
        app.dependency_overrides.clear()

    assert latest.status_code == 200
    body = latest.json()
    assert body["target_session_date"] == "2026-09-18"
    assert body["picks"][0]["ticker"] == "AAA"
    assert body["picks"][0]["evidence"][0]["title"] == "Headline a"
    assert body["picks"][0]["hit"] is None  # result fields stay empty until the session closes
    assert history.status_code == 200
    assert [r["target_session_date"] for r in history.json()["runs"]] == ["2026-09-18"]
    assert "hit_rate" in history.json()["performance"]
