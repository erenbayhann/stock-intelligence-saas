import logging
import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.news import NewsArticle, NewsCompanyLink
from app.models.security import Security
from app.providers.llm.news_extractor import ClaudeNewsExtractor, LLMProviderError
from app.providers.news.base import NewsProvider, RawArticle
from app.services.data_quality_service import record_alert
from app.services.label_service import compute_realized_label, next_trading_session_after

logger = logging.getLogger(__name__)

_PARENTHETICAL_SUFFIX = re.compile(r"\s*\([^)]*\)\s*$")

TOP_NEWS_LOOKBACK_HOURS = 48
NEWS_HISTORY_DAYS = 7
NEWS_HISTORY_PER_DAY_LIMIT = 5


def build_ticker_search_phrases(db: Session) -> dict[str, str]:
    """ticker -> search phrase for GDELT batched queries. A bare 1-2 letter
    ticker ('V', 'T', 'MA') is a poor/ambiguous search term, so this uses the
    company's display name with any trailing parenthetical (share class,
    "(The)") stripped, e.g. "Alphabet Inc. (Class A)" -> "Alphabet Inc.".
    """
    rows = db.execute(
        select(Security.ticker, Company.name)
        .join(Company, Security.company_id == Company.id)
        .where(Security.is_active.is_(True))
    ).all()
    return {ticker: _PARENTHETICAL_SUFFIX.sub("", name).strip() for ticker, name in rows}


def ingest_from_provider(
    db: Session, provider: NewsProvider, since: datetime, tickers: dict[str, str] | None = None
) -> list[RawArticle]:
    """Fetches from one provider and returns the raw articles — normalization/
    storage happens separately in `store_articles` so callers can merge
    multiple providers before deduping.
    """
    return provider.fetch_articles(since, tickers=tickers)


def store_articles(
    db: Session, articles: list[RawArticle], ticker_to_security_id: dict[str, int]
) -> dict[str, int]:
    """Normalizes, dedupes, and idempotently upserts raw articles into
    news_articles + news_company_links (spec §5/§17).

    Dedup strategy: (source, source_article_id) is a DB-level unique
    constraint for providers with a stable id (Marketaux). GDELT has no
    stable per-article id, so its articles are deduped by URL against
    already-stored rows before insert — a second pass across *both* sources
    together, since the same wire story often appears via more than one
    provider (spec §5).
    """
    inserted = 0
    skipped_duplicate = 0
    links_created = 0

    existing_urls = {row for row in db.scalars(select(NewsArticle.url))}

    for article in articles:
        if article.url in existing_urls:
            skipped_duplicate += 1
            continue

        news_article = NewsArticle(
            source=article.source,
            source_article_id=article.source_article_id,
            title=article.title,
            url=article.url,
            published_time=article.published_time,
            raw_payload=article.raw_payload,
        )
        db.add(news_article)
        try:
            db.flush()
        except IntegrityError:
            # Unique (source, source_article_id) hit — another row already
            # covers this article; treat as a duplicate, not a failure.
            db.rollback()
            skipped_duplicate += 1
            continue

        existing_urls.add(article.url)
        inserted += 1

        for ticker in article.matched_tickers:
            security_id = ticker_to_security_id.get(ticker)
            if security_id is None:
                continue
            db.add(
                NewsCompanyLink(
                    news_article_id=news_article.id,
                    security_id=security_id,
                    relevance=article.ticker_relevance.get(ticker, 1.0),
                )
            )
            links_created += 1

    db.commit()
    logger.info(
        "store_articles: %d inserted, %d duplicates skipped, %d company links created",
        inserted,
        skipped_duplicate,
        links_created,
    )
    return {"inserted": inserted, "skipped_duplicate": skipped_duplicate, "links_created": links_created}


def load_company_universe(db: Session) -> list[tuple[str, str, str | None]]:
    """(ticker, company_name, sector) for every active security — the full
    context classify_unprocessed_articles gives the LLM, so it can reason
    about content/sector relevance instead of being limited to whatever a
    literal company-name substring match already found upstream.
    """
    rows = db.execute(
        select(Security.ticker, Company.name, Company.sector)
        .join(Company, Security.company_id == Company.id)
        .where(Security.is_active.is_(True))
    ).all()
    return [(ticker, name, sector) for ticker, name, sector in rows]


def classify_unprocessed_articles(
    db: Session,
    extractor: ClaudeNewsExtractor,
    limit: int = 200,
    job_run_id: int | None = None,
) -> dict:
    """Runs full-universe LLM classification (spec §5, extended 2026-09-14)
    on articles that haven't been classified yet. Unlike the literal
    company-name substring matching providers do at fetch time (see
    app/providers/news/*), this sees every active ticker and can attach a
    headline to companies it never names — a commodity-price move to its
    producers, a regulatory change to its whole affected sector, etc.

    A failed classification never crashes the job: the article's
    classified_at stays NULL (so it's retried on a later run), a
    data_quality_alerts row is logged, and the loop continues (spec §5's
    LLM failure handling). Links from provider-level matching already exist
    with relevance but NULL sentiment/category/importance — this upserts
    those with real per-ticker values and can add further links the
    substring match missed, never removes one.
    """
    articles = db.scalars(
        select(NewsArticle)
        .where(NewsArticle.classified_at.is_(None), NewsArticle.is_duplicate_of.is_(None))
        .order_by(NewsArticle.published_time.desc())
        .limit(limit)
    ).all()

    universe = load_company_universe(db)
    ticker_to_security_id = {
        ticker: security_id
        for ticker, security_id in db.execute(
            select(Security.ticker, Security.id).where(Security.is_active.is_(True))
        )
    }

    classified = 0
    failed = 0
    links_created = 0
    tokens_in_total = 0
    tokens_out_total = 0

    for article in articles:
        try:
            result = extractor.classify(title=article.title, source=article.source, universe=universe)
        except LLMProviderError as exc:
            failed += 1
            record_alert(
                db,
                severity="error",
                category="llm_provider_error",
                message=f"LLM classification failed for news_article {article.id}: {exc}",
                detail={"kind": exc.kind, "news_article_id": article.id},
                job_run_id=job_run_id,
            )
            continue

        for item in result.tickers:
            security_id = ticker_to_security_id.get(item.ticker)
            if security_id is None:
                continue
            stmt = insert(NewsCompanyLink).values(
                news_article_id=article.id,
                security_id=security_id,
                relevance=item.relevance,
                sentiment=item.sentiment,
                event_category=item.event_category,
                importance=item.importance,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["news_article_id", "security_id"],
                set_={
                    "relevance": stmt.excluded.relevance,
                    "sentiment": stmt.excluded.sentiment,
                    "event_category": stmt.excluded.event_category,
                    "importance": stmt.excluded.importance,
                },
            )
            db.execute(stmt)
            links_created += 1

        article.classified_at = datetime.now(timezone.utc)
        db.commit()
        classified += 1
        tokens_in_total += result.tokens_in
        tokens_out_total += result.tokens_out

    return {
        "classified": classified,
        "failed": failed,
        "llm_links_created": links_created,
        "llm_tokens_in": tokens_in_total,
        "llm_tokens_out": tokens_out_total,
    }


_NEUTRAL_SENTIMENT_THRESHOLD = 0.15  # matches SentimentBadge's neutral cutoff on the frontend


def _news_item(article: NewsArticle, link: NewsCompanyLink, ticker: str, name: str, outcome: dict | None = None) -> dict:
    item = {
        "ticker": ticker,
        "company_name": name,
        "title": article.title,
        "url": article.url,
        "source": article.source,
        "published_time": article.published_time,
        "sentiment": float(link.sentiment) if link.sentiment is not None else None,
        "event_category": link.event_category,
        "importance": float(link.importance),
        "score": round(float(link.relevance or 0) * float(link.importance), 4),
    }
    item.update(outcome or _PENDING_OUTCOME)
    return item


_PENDING_OUTCOME = {"actual_return": None, "benchmark_return": None, "direction_correct": None}


def _realized_outcome(
    db: Session, security_id: int, published_time: datetime, sentiment: float | None
) -> dict:
    """Did the stock's own next-session return actually move the direction
    this headline's sentiment implied? A separate, honest evaluation of the
    news signal itself — never fed back into train_model/generate_predictions
    (spec §12/§15 exclude news from the ranking model's own feature set until
    its rollout bar is met; this is unrelated, purely a display-side check).
    Reports the stock's own realized return AND the benchmark's own realized
    return side by side (not a pre-computed excess/difference) — more
    directly readable than an abstract "vs S&P 500" delta. direction_correct
    is still graded against the stock's own return direction, not excess vs.
    benchmark, because sentiment is a claim about this specific stock's
    reaction, not a claim about beating the market. Every field is None when
    the reacting session hasn't closed yet (this is time-based, not tab-based
    — an article from earlier today can already have a closed reacting
    session by evening, so this runs for get_top_news too, not just history),
    or direction_correct alone is None when sentiment is too close to neutral
    to make a directional claim at all.
    """
    session_date = next_trading_session_after(db, published_time)
    if session_date is None:
        return dict(_PENDING_OUTCOME)

    label = compute_realized_label(db, security_id, session_date)
    if label is None:
        return dict(_PENDING_OUTCOME)

    direction_correct = None
    if sentiment is not None and abs(sentiment) >= _NEUTRAL_SENTIMENT_THRESHOLD:
        direction_correct = (sentiment > 0) == (label["actual_return"] > 0)

    return {
        "actual_return": label["actual_return"],
        "benchmark_return": label["benchmark_return"],
        "direction_correct": direction_correct,
    }


def get_top_news(db: Session, limit: int = 20) -> list[dict]:
    """Independent of the ranking model (spec §12/§15) — this surfaces
    whichever classified headlines the LLM itself scored as most
    relevant+important for a company in the last TOP_NEWS_LOOKBACK_HOURS,
    ranked by relevance x importance. Not a prediction and not fed into
    train_model/generate_predictions; a same-day news salience digest only.
    Also attaches the realized outcome per item, same as get_news_history —
    an article from earlier in the lookback window can already have a
    closed reacting session by the time this is called.
    """
    since = datetime.now(timezone.utc) - timedelta(hours=TOP_NEWS_LOOKBACK_HOURS)
    score = NewsCompanyLink.relevance * NewsCompanyLink.importance

    rows = db.execute(
        select(NewsArticle, NewsCompanyLink, Security.ticker, Company.name)
        .join(NewsCompanyLink, NewsCompanyLink.news_article_id == NewsArticle.id)
        .join(Security, Security.id == NewsCompanyLink.security_id)
        .join(Company, Company.id == Security.company_id)
        .where(
            NewsArticle.is_duplicate_of.is_(None),
            NewsArticle.published_time >= since,
            NewsCompanyLink.importance.is_not(None),
        )
        .order_by(score.desc())
        .limit(limit)
    ).all()

    items = []
    for article, link, ticker, name in rows:
        sentiment = float(link.sentiment) if link.sentiment is not None else None
        outcome = _realized_outcome(db, link.security_id, article.published_time, sentiment)
        items.append(_news_item(article, link, ticker, name, outcome))
    return items


def get_news_history(
    db: Session, days: int = NEWS_HISTORY_DAYS, per_day_limit: int = NEWS_HISTORY_PER_DAY_LIMIT
) -> list[dict]:
    """"Last 7 Days" browse view for the news digest — same relevance x
    importance scoring as get_top_news, but bucketed by calendar day for the
    trailing `days` days *before* today (today is already covered by the
    "Today" view, get_top_news). Independent of the ranking model, same as
    get_top_news — this never feeds train_model/generate_predictions.
    """
    today = datetime.now(timezone.utc).date()
    start = datetime.combine(today - timedelta(days=days), datetime.min.time(), tzinfo=timezone.utc)
    end = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)

    rows = db.execute(
        select(NewsArticle, NewsCompanyLink, Security.ticker, Company.name)
        .join(NewsCompanyLink, NewsCompanyLink.news_article_id == NewsArticle.id)
        .join(Security, Security.id == NewsCompanyLink.security_id)
        .join(Company, Company.id == Security.company_id)
        .where(
            NewsArticle.is_duplicate_of.is_(None),
            NewsArticle.published_time >= start,
            NewsArticle.published_time < end,
            NewsCompanyLink.importance.is_not(None),
        )
    ).all()

    by_day: dict[str, list[tuple]] = {}
    for article, link, ticker, name in rows:
        day_key = article.published_time.date().isoformat()
        by_day.setdefault(day_key, []).append((article, link, ticker, name))

    def _row_score(row: tuple) -> float:
        _, link, _, _ = row
        return float(link.relevance or 0) * float(link.importance)

    result = []
    for day, day_rows in sorted(by_day.items(), reverse=True):
        # Outcome-lookup queries only run for the rows that actually survive
        # the per-day cut, not every classified link that day.
        top_rows = sorted(day_rows, key=_row_score, reverse=True)[:per_day_limit]
        items = []
        for article, link, ticker, name in top_rows:
            sentiment = float(link.sentiment) if link.sentiment is not None else None
            outcome = _realized_outcome(db, link.security_id, article.published_time, sentiment)
            items.append(_news_item(article, link, ticker, name, outcome))
        result.append({"date": day, "items": items})
    return result


def get_news_stats(db: Session, days: int = NEWS_HISTORY_DAYS) -> dict:
    """Aggregate track-record stats over the trailing `days` days —
    deliberately over EVERY classified (article, company) link in the
    window, not just whatever's currently surfaced in the top-5-per-day
    digest, so this reflects genuine volume/accuracy rather than a tiny,
    5-item sample that swings wildly (e.g. 100% or 0% from one call).
    """
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(NewsArticle, NewsCompanyLink)
        .join(NewsCompanyLink, NewsCompanyLink.news_article_id == NewsArticle.id)
        .where(
            NewsArticle.is_duplicate_of.is_(None),
            NewsArticle.published_time >= since,
            NewsCompanyLink.importance.is_not(None),
        )
    ).all()

    graded = 0
    correct = 0
    for article, link in rows:
        sentiment = float(link.sentiment) if link.sentiment is not None else None
        outcome = _realized_outcome(db, link.security_id, article.published_time, sentiment)
        if outcome["direction_correct"] is not None:
            graded += 1
            if outcome["direction_correct"]:
                correct += 1

    return {
        "total_classified": len(rows),
        "graded": graded,
        "accuracy_pct": (correct / graded) if graded > 0 else None,
    }
