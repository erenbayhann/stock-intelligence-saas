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

logger = logging.getLogger(__name__)

_PARENTHETICAL_SUFFIX = re.compile(r"\s*\([^)]*\)\s*$")

TOP_NEWS_LOOKBACK_HOURS = 48


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


def get_top_news(db: Session, limit: int = 20) -> list[dict]:
    """Independent of the ranking model (spec §12/§15) — this surfaces
    whichever classified headlines the LLM itself scored as most
    relevant+important for a company in the last TOP_NEWS_LOOKBACK_HOURS,
    ranked by relevance x importance. Not a prediction and not fed into
    train_model/generate_predictions; a same-day news salience digest only.
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

    return [
        {
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
        for article, link, ticker, name in rows
    ]
