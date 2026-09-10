import logging
import re
from datetime import datetime

from sqlalchemy import select
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
                    news_article_id=news_article.id, security_id=security_id, relevance=1.0
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


def enrich_unprocessed_articles(
    db: Session,
    extractor: ClaudeNewsExtractor,
    limit: int = 200,
    job_run_id: int | None = None,
) -> dict:
    """Runs LLM extraction (spec §5) on articles that don't have it yet.
    A failed extraction never crashes the job: the article keeps NULL
    sentiment/event_category/importance, a data_quality_alerts row is logged,
    and the loop continues (spec §5's LLM failure handling).
    """
    articles = db.scalars(
        select(NewsArticle)
        .where(NewsArticle.sentiment.is_(None), NewsArticle.is_duplicate_of.is_(None))
        .order_by(NewsArticle.published_time.desc())
        .limit(limit)
    ).all()

    enriched = 0
    failed = 0
    tokens_in_total = 0
    tokens_out_total = 0

    for article in articles:
        company_names = db.execute(
            select(Company.name, Security.ticker)
            .join(NewsCompanyLink, NewsCompanyLink.security_id == Security.id)
            .join(Company, Security.company_id == Company.id)
            .where(NewsCompanyLink.news_article_id == article.id)
        ).first()
        company_name, ticker = company_names if company_names else ("Unknown company", "")

        try:
            extraction = extractor.extract(
                title=article.title, source=article.source, company_name=company_name, ticker=ticker
            )
        except LLMProviderError as exc:
            failed += 1
            record_alert(
                db,
                severity="error",
                category="llm_provider_error",
                message=f"LLM extraction failed for news_article {article.id}: {exc}",
                detail={"kind": exc.kind, "news_article_id": article.id},
                job_run_id=job_run_id,
            )
            continue

        article.sentiment = extraction.sentiment
        article.event_category = extraction.event_category
        article.importance = extraction.importance
        db.commit()
        enriched += 1
        tokens_in_total += extraction.tokens_in
        tokens_out_total += extraction.tokens_out

    return {
        "enriched": enriched,
        "failed": failed,
        "llm_tokens_in": tokens_in_total,
        "llm_tokens_out": tokens_out_total,
    }
