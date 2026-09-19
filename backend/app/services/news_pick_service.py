"""News picks — a second, independent daily top-5 that follows the ranking
model's exact cycle but ranks stocks purely by classified news.

Cycle (identical to prediction_runs, spec §11/§13): the picks for a session
are locked once, shortly before the 09:30 ET open (~09:15 ET), from ONLY the
news that had already been published AND classified by that moment; the row
is never modified afterwards; after the session closes the realized result
is written once.

Score: for each S&P 100 stock, the sum over the window of
sentiment x importance x relevance for every classified headline linked to
it. Only stocks with a net-POSITIVE score are ever picked (these are
bullish picks — a stock with net-negative news is never listed as one), so
fewer than 5 picks is a real, honest outcome on a quiet-news day.
"""

import logging
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.market_price import MarketPrice
from app.models.news import NewsArticle, NewsCompanyLink
from app.models.news_pick import NewsPick, NewsPickResult, NewsPickRun
from app.models.security import Security
from app.services.label_service import BENCHMARK_TICKER, compute_realized_label

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
TOP_N = 5
MAX_EVIDENCE = 3
LOCK_HOUR_ET = 9
LOCK_MINUTE_ET = 15
MARKET_CLOSE_HOUR_ET = 16
FALLBACK_WINDOW = timedelta(hours=24)  # when no prior session is on record
MAX_WINDOW = timedelta(days=5)  # long weekend + holiday, never more
# A run written this long after its information cutoff was reconstructed
# after the fact (see generate_news_pick_run), not locked live.
RECONSTRUCTED_AFTER = timedelta(minutes=30)
PERFORMANCE_WINDOW_DAYS = 7


class NewsPicksAlreadyExistError(Exception):
    pass


def lock_moment(target_session_date: date) -> datetime:
    """The ~09:15 ET pre-market lock for a session, as UTC."""
    return datetime(
        target_session_date.year, target_session_date.month, target_session_date.day,
        LOCK_HOUR_ET, LOCK_MINUTE_ET, tzinfo=ET,
    ).astimezone(timezone.utc)


def _window_start(db: Session, target_session_date: date, as_of: datetime) -> datetime:
    """News window opens at the previous regular session's real ~16:00 ET
    close (news the market has already had a chance to react to at a
    session is excluded), taken from the benchmark's own trading calendar.
    """
    benchmark = db.scalar(select(Security).where(Security.ticker == BENCHMARK_TICKER))
    prior_bar_ts = None
    if benchmark is not None:
        prior_bar_ts = db.scalar(
            select(func.max(MarketPrice.ts)).where(
                MarketPrice.security_id == benchmark.id,
                MarketPrice.session_type == "regular",
                MarketPrice.ts < datetime.combine(target_session_date, time.min, tzinfo=timezone.utc),
            )
        )
    if prior_bar_ts is None:
        return as_of - FALLBACK_WINDOW

    prior_date = prior_bar_ts.date()
    prior_close = datetime(
        prior_date.year, prior_date.month, prior_date.day, MARKET_CLOSE_HOUR_ET, tzinfo=ET
    ).astimezone(timezone.utc)
    return max(prior_close, as_of - MAX_WINDOW)


def _score_candidates(
    db: Session, universe_tickers: set[str], window_start: datetime, as_of: datetime
) -> list[dict]:
    """Every stock with any classified news in (window_start, as_of], scored.
    Point-in-time: an article only counts if it was published AND classified
    at or before as_of — never information that didn't exist yet.
    """
    rows = db.execute(
        select(NewsArticle, NewsCompanyLink, Security.id, Security.ticker, Company.name)
        .join(NewsCompanyLink, NewsCompanyLink.news_article_id == NewsArticle.id)
        .join(Security, Security.id == NewsCompanyLink.security_id)
        .join(Company, Company.id == Security.company_id)
        .where(
            Security.is_active.is_(True),
            Security.ticker.in_(universe_tickers),
            NewsArticle.is_duplicate_of.is_(None),
            NewsArticle.classified_at.is_not(None),
            NewsArticle.classified_at <= as_of,
            NewsArticle.published_time > window_start,
            NewsArticle.published_time <= as_of,
            NewsCompanyLink.importance.is_not(None),
            NewsCompanyLink.sentiment.is_not(None),
        )
    ).all()

    per_security: dict[int, dict] = {}
    for article, link, security_id, ticker, company_name in rows:
        sentiment = float(link.sentiment)
        importance = float(link.importance)
        relevance = float(link.relevance or 0)
        contribution = sentiment * importance * relevance

        entry = per_security.setdefault(
            security_id,
            {
                "security_id": security_id, "ticker": ticker, "company_name": company_name,
                "news_score": 0.0, "article_count": 0, "positive_count": 0, "negative_count": 0,
                "sentiment_sum": 0.0, "evidence": [],
            },
        )
        entry["news_score"] += contribution
        entry["article_count"] += 1
        entry["sentiment_sum"] += sentiment
        if contribution > 0:
            entry["positive_count"] += 1
            entry["evidence"].append({
                "news_article_id": article.id,
                "title": article.title,
                "url": article.url,
                "source": article.source,
                "published_time": article.published_time.isoformat(),
                "sentiment": round(sentiment, 3),
                "importance": round(importance, 3),
                "contribution": round(contribution, 4),
            })
        elif contribution < 0:
            entry["negative_count"] += 1

    return list(per_security.values())


def generate_news_pick_run(
    db: Session,
    universe_tickers: set[str],
    target_session_date: date | None = None,
    as_of: datetime | None = None,
) -> dict:
    """Locks the news picks for a session. Live use passes neither argument
    (target = today in ET, cutoff = now). A run for a session whose lock
    moment already passed can be reconstructed by passing that session's
    date and lock_moment() as as_of: the selection still uses only news
    classified by that cutoff, and the row records honestly that it was
    written later (generated_at vs as_of — exposed as `reconstructed`).
    Idempotent per session, like the ranking model's final run.
    """
    now = datetime.now(timezone.utc)
    target_session_date = target_session_date or now.astimezone(ET).date()
    as_of = as_of or now

    existing = db.scalar(
        select(NewsPickRun).where(NewsPickRun.target_session_date == target_session_date)
    )
    if existing is not None:
        raise NewsPicksAlreadyExistError(
            f"News picks already exist for {target_session_date} (id={existing.id})"
        )

    window_start = _window_start(db, target_session_date, as_of)
    candidates = _score_candidates(db, universe_tickers, window_start, as_of)
    top = sorted(
        (c for c in candidates if c["news_score"] > 0),
        key=lambda c: (-c["news_score"], -c["article_count"], c["ticker"]),
    )[:TOP_N]

    run = NewsPickRun(
        target_session_date=target_session_date, generated_at=now, as_of=as_of,
        window_start=window_start, candidates_scored=len(candidates),
    )
    db.add(run)
    db.flush()

    for rank, candidate in enumerate(top, start=1):
        evidence = sorted(candidate["evidence"], key=lambda e: e["contribution"], reverse=True)
        db.add(NewsPick(
            run_id=run.id, security_id=candidate["security_id"], rank=rank,
            news_score=round(candidate["news_score"], 4),
            article_count=candidate["article_count"],
            positive_count=candidate["positive_count"],
            negative_count=candidate["negative_count"],
            avg_sentiment=round(candidate["sentiment_sum"] / candidate["article_count"], 3),
            evidence=evidence[:MAX_EVIDENCE],
        ))
    db.commit()

    return {
        "news_pick_run_id": run.id,
        "target_session_date": target_session_date.isoformat(),
        "candidates_scored": len(candidates),
        "picks": [{"rank": i, "ticker": c["ticker"], "news_score": round(c["news_score"], 4)}
                  for i, c in enumerate(top, start=1)],
    }


def evaluate_pending_news_picks(db: Session) -> dict:
    """After a session closes, write each pick's realized result exactly
    once. A pick whose session has no closing bar yet is correctly left
    pending, never fabricated (spec §27) — compute_realized_label returns
    None in that case.
    """
    pending = db.execute(
        select(NewsPick.id, NewsPick.security_id, NewsPickRun.target_session_date)
        .join(NewsPickRun, NewsPick.run_id == NewsPickRun.id)
        .outerjoin(NewsPickResult, NewsPickResult.pick_id == NewsPick.id)
        .where(NewsPickResult.id.is_(None))
    ).all()

    evaluated = 0
    not_yet_closed = 0
    for pick_id, security_id, target_session_date in pending:
        label = compute_realized_label(db, security_id, target_session_date)
        if label is None:
            not_yet_closed += 1
            continue
        db.add(NewsPickResult(
            pick_id=pick_id,
            actual_return=label["actual_return"],
            benchmark_return=label["benchmark_return"],
            excess_return=label["actual_excess_return"],
            hit=label["actual_excess_return"] > 0,
            evaluated_at=datetime.now(timezone.utc),
        ))
        evaluated += 1

    db.commit()
    logger.info("evaluate_pending_news_picks: %d evaluated, %d not yet closed", evaluated, not_yet_closed)
    return {"news_picks_evaluated": evaluated, "news_picks_not_yet_closed": not_yet_closed}


def _run_payload(db: Session, run: NewsPickRun) -> dict:
    rows = db.execute(
        select(NewsPick, Security.ticker, Company.name, NewsPickResult)
        .join(Security, Security.id == NewsPick.security_id)
        .join(Company, Company.id == Security.company_id)
        .outerjoin(NewsPickResult, NewsPickResult.pick_id == NewsPick.id)
        .where(NewsPick.run_id == run.id)
        .order_by(NewsPick.rank)
    ).all()

    picks = []
    graded = 0
    hits = 0
    benchmark_return = None
    for pick, ticker, company_name, result in rows:
        item = {
            "rank": pick.rank, "ticker": ticker, "company_name": company_name,
            "news_score": float(pick.news_score),
            "article_count": pick.article_count,
            "positive_count": pick.positive_count,
            "negative_count": pick.negative_count,
            "avg_sentiment": float(pick.avg_sentiment),
            "evidence": pick.evidence,
            "actual_return": None, "benchmark_return": None, "excess_return": None, "hit": None,
        }
        if result is not None:
            item["actual_return"] = float(result.actual_return)
            item["benchmark_return"] = float(result.benchmark_return)
            item["excess_return"] = float(result.excess_return)
            item["hit"] = result.hit
            benchmark_return = float(result.benchmark_return)
            graded += 1
            hits += int(result.hit)
        picks.append(item)

    return {
        "target_session_date": run.target_session_date,
        "generated_at": run.generated_at,
        "as_of": run.as_of,
        "window_start": run.window_start,
        "candidates_scored": run.candidates_scored,
        "reconstructed": (run.generated_at - run.as_of) > RECONSTRUCTED_AFTER,
        "benchmark_return": benchmark_return,
        "hit_rate": (hits / graded) if graded else None,
        "picks": picks,
    }


def get_latest_news_picks(db: Session) -> dict | None:
    run = db.scalar(select(NewsPickRun).order_by(NewsPickRun.target_session_date.desc()).limit(1))
    return _run_payload(db, run) if run is not None else None


def get_news_pick_history(db: Session, limit: int = 7) -> list[dict]:
    runs = db.scalars(
        select(NewsPickRun).order_by(NewsPickRun.target_session_date.desc()).limit(limit)
    ).all()
    return [_run_payload(db, run) for run in runs]


def news_pick_performance(
    db: Session, days: int = PERFORMANCE_WINDOW_DAYS, today: date | None = None
) -> dict:
    """Aggregate track record over every pick in the trailing window — only
    picks whose result actually exists count as graded; a still-open pick
    is structurally excluded (no result row), never assumed."""
    today = today or datetime.now(timezone.utc).astimezone(ET).date()
    since = today - timedelta(days=days)
    rows = db.execute(
        select(
            NewsPickRun.target_session_date,
            NewsPickResult.actual_return, NewsPickResult.benchmark_return,
            NewsPickResult.excess_return, NewsPickResult.hit,
        )
        .select_from(NewsPick)
        .join(NewsPickRun, NewsPick.run_id == NewsPickRun.id)
        .outerjoin(NewsPickResult, NewsPickResult.pick_id == NewsPick.id)
        .where(NewsPickRun.target_session_date >= since)
    ).all()

    graded = [r for r in rows if r.hit is not None]
    if not graded:
        return {
            "window_days": days, "n_picks": len(rows), "n_graded": 0, "n_days": 0,
            "hit_rate": None, "mean_actual_return": None,
            "mean_benchmark_return": None, "mean_excess_return": None,
        }

    def _mean(values: list[float]) -> float:
        return sum(values) / len(values)

    return {
        "window_days": days,
        "n_picks": len(rows),
        "n_graded": len(graded),
        "n_days": len({r.target_session_date for r in graded}),
        "hit_rate": sum(1 for r in graded if r.hit) / len(graded),
        "mean_actual_return": _mean([float(r.actual_return) for r in graded]),
        "mean_benchmark_return": _mean([float(r.benchmark_return) for r in graded]),
        "mean_excess_return": _mean([float(r.excess_return) for r in graded]),
    }
