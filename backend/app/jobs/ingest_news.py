"""CLI entrypoint: python -m app.jobs.ingest_news

Pulls recent news from GDELT (per-ticker batched + thematic) and Marketaux
(broad market), normalizes/dedupes into news_articles + news_company_links,
then runs Claude Haiku 4.5 extraction (spec §5) on whatever doesn't have it
yet. Every provider/LLM failure is logged as a data_quality_alerts row and
never crashes the job — see app.services.news_service.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.models.security import Security
from app.providers.llm.news_extractor import ClaudeNewsExtractor, estimate_cost_usd
from app.providers.news.alpha_vantage import AlphaVantageNewsProvider
from app.providers.news.base import RawArticle
from app.providers.news.gdelt import GDELTNewsProvider
from app.providers.news.marketaux import MarketauxNewsProvider
from app.services.data_quality_service import record_alert
from app.services.job_run_service import track_job_run
from app.services.news_service import (
    build_ticker_search_phrases,
    enrich_unprocessed_articles,
    store_articles,
)

logger = logging.getLogger(__name__)

JOB_NAME = "news_ingestion"

MACRO_KEYWORDS = [
    "Federal Reserve",
    "interest rate",
    "inflation report",
    "S&P 500",
    "stock market",
]


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    db = SessionLocal()
    try:
        with track_job_run(db, JOB_NAME) as job_run:
            since = datetime.now(timezone.utc) - timedelta(hours=settings.news_lookback_hours)
            ticker_phrases = build_ticker_search_phrases(db)

            gdelt = GDELTNewsProvider()
            all_articles: list[RawArticle] = []

            try:
                all_articles.extend(gdelt.fetch_articles(since, tickers=ticker_phrases))
            except Exception as exc:
                record_alert(
                    db,
                    severity="error",
                    category="provider_error",
                    message=f"GDELT per-ticker fetch failed: {exc}",
                    job_run_id=job_run.id,
                )
            if gdelt.last_failed_tickers:
                record_alert(
                    db,
                    severity="warning",
                    category="provider_error",
                    message=f"GDELT per-ticker fetch: {len(gdelt.last_failed_tickers)} batch(es) failed after retries",
                    detail={"failed_tickers": gdelt.last_failed_tickers},
                    job_run_id=job_run.id,
                )

            try:
                all_articles.extend(gdelt.fetch_thematic(since, MACRO_KEYWORDS))
            except Exception as exc:
                record_alert(
                    db,
                    severity="error",
                    category="provider_error",
                    message=f"GDELT thematic fetch failed: {exc}",
                    job_run_id=job_run.id,
                )

            if settings.marketaux_api_key:
                try:
                    marketaux = MarketauxNewsProvider(api_key=settings.marketaux_api_key)
                    all_articles.extend(marketaux.fetch_articles(since))
                except Exception as exc:
                    record_alert(
                        db,
                        severity="error",
                        category="provider_error",
                        message=f"Marketaux fetch failed: {exc}",
                        job_run_id=job_run.id,
                    )

            if settings.alpha_vantage_api_key:
                alpha_vantage = AlphaVantageNewsProvider(api_key=settings.alpha_vantage_api_key)
                try:
                    all_articles.extend(alpha_vantage.fetch_articles(since, tickers=ticker_phrases))
                except Exception as exc:
                    record_alert(
                        db,
                        severity="error",
                        category="provider_error",
                        message=f"Alpha Vantage fetch failed: {exc}",
                        job_run_id=job_run.id,
                    )
                if alpha_vantage.last_rate_limited:
                    record_alert(
                        db,
                        severity="warning",
                        category="provider_error",
                        message="Alpha Vantage NEWS_SENTIMENT rate-limited (daily/per-second free-tier cap) — some or all batches returned no data",
                        job_run_id=job_run.id,
                    )

            ticker_to_security_id = {
                s.ticker: s.id for s in db.scalars(select(Security).where(Security.is_active.is_(True)))
            }
            store_result = store_articles(db, all_articles, ticker_to_security_id)

            enrich_result = {"enriched": 0, "failed": 0, "llm_tokens_in": 0, "llm_tokens_out": 0}
            if settings.anthropic_api_key:
                extractor = ClaudeNewsExtractor(
                    api_key=settings.anthropic_api_key, model=settings.news_llm_model
                )
                enrich_result = enrich_unprocessed_articles(db, extractor, job_run_id=job_run.id)

            llm_cost_usd = estimate_cost_usd(
                enrich_result["llm_tokens_in"], enrich_result["llm_tokens_out"]
            )
            job_run.job_metadata = {
                "articles_fetched": len(all_articles),
                **store_result,
                **enrich_result,
                "llm_cost_usd": round(llm_cost_usd, 6),
            }
            result = job_run.job_metadata
    finally:
        db.close()

    logger.info("Done: %s", result)


if __name__ == "__main__":
    main()
