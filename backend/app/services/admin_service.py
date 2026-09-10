from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.api_credit_topup import ApiCreditTopup
from app.models.job_run import JobRun
from app.models.news import NewsArticle
from app.services.label_service import get_trading_days

NEWS_ROLLOUT_WINDOW_DAYS = 60
NEWS_ROLLOUT_THRESHOLD_PCT = 0.80
LOW_BALANCE_WARNING_DAYS = 14
BURN_RATE_LOOKBACK_DAYS = 30


def news_rollout_progress(db: Session) -> dict:
    """spec §15: real, live-collected news coverage over the trailing
    60-trading-day window — not a calendar date. A trading day counts as
    "covered" if at least one real news article was published that day
    (the simplest defensible reading of "real news coverage exists" from
    spec §15; day-level presence, not per-ticker breadth).
    """
    end = date.today()
    start = end - timedelta(days=NEWS_ROLLOUT_WINDOW_DAYS * 2)  # generous calendar buffer for trading-day lookup
    trading_days = get_trading_days(db, start, end)[-NEWS_ROLLOUT_WINDOW_DAYS:]

    if not trading_days:
        return {
            "eligible": False, "trading_days_covered": 0, "trading_days_required": NEWS_ROLLOUT_WINDOW_DAYS,
            "window_size": NEWS_ROLLOUT_WINDOW_DAYS, "coverage_pct": 0.0, "estimated_eligible_date": None,
        }

    covered_dates = set(
        db.scalars(
            select(NewsArticle.published_time).where(
                NewsArticle.published_time >= datetime.combine(trading_days[0], datetime.min.time(), tzinfo=timezone.utc),
                NewsArticle.published_time <= datetime.combine(trading_days[-1], datetime.max.time(), tzinfo=timezone.utc),
            )
        )
    )
    covered_calendar_dates = {ts.date() for ts in covered_dates}
    days_covered = sum(1 for d in trading_days if d in covered_calendar_dates)
    coverage_pct = days_covered / len(trading_days)
    eligible = coverage_pct >= NEWS_ROLLOUT_THRESHOLD_PCT

    estimated_eligible_date = None
    if not eligible and days_covered > 0:
        # crude linear projection: at the current rate of accumulating
        # covered days, how many more calendar days until we cross 80%?
        rate_per_day = days_covered / len(trading_days)
        days_needed = (NEWS_ROLLOUT_THRESHOLD_PCT * NEWS_ROLLOUT_WINDOW_DAYS - days_covered) / max(rate_per_day, 1e-6)
        estimated_eligible_date = (end + timedelta(days=int(days_needed))).isoformat()

    return {
        "eligible": eligible,
        "trading_days_covered": days_covered,
        "trading_days_required": int(NEWS_ROLLOUT_THRESHOLD_PCT * NEWS_ROLLOUT_WINDOW_DAYS),
        "window_size": len(trading_days),
        "coverage_pct": coverage_pct,
        "estimated_eligible_date": estimated_eligible_date,
    }


def record_credit_topup(db: Session, amount_usd: float, topped_up_at: datetime, note: str | None) -> ApiCreditTopup:
    topup = ApiCreditTopup(amount_usd=amount_usd, topped_up_at=topped_up_at, note=note)
    db.add(topup)
    db.commit()
    return topup


def credit_status(db: Session) -> dict:
    """spec §15: Anthropic's API is prepaid with no balance-read endpoint, so
    remaining balance is estimated as recorded top-ups minus logged spend
    (job_runs.metadata.llm_cost_usd for job_name='news_ingestion', per that
    job's own convention — see app/jobs/ingest_news.py).
    """
    total_topped_up = sum(float(a) for a in db.scalars(select(ApiCreditTopup.amount_usd)).all())

    all_news_jobs = db.scalars(
        select(JobRun).where(JobRun.job_name == "news_ingestion", JobRun.status == "success")
    ).all()
    total_spent = sum(float((j.job_metadata or {}).get("llm_cost_usd", 0) or 0) for j in all_news_jobs)

    cutoff = datetime.now(timezone.utc) - timedelta(days=BURN_RATE_LOOKBACK_DAYS)
    recent_spend = sum(
        float((j.job_metadata or {}).get("llm_cost_usd", 0) or 0)
        for j in all_news_jobs
        if j.started_at >= cutoff
    )
    trailing_daily_burn = recent_spend / BURN_RATE_LOOKBACK_DAYS if all_news_jobs else None

    remaining = total_topped_up - total_spent
    estimated_days_until_depleted = None
    if trailing_daily_burn and trailing_daily_burn > 0:
        estimated_days_until_depleted = remaining / trailing_daily_burn

    low_balance_warning = (
        estimated_days_until_depleted is not None and estimated_days_until_depleted < LOW_BALANCE_WARNING_DAYS
    )

    return {
        "estimated_remaining_usd": remaining,
        "total_topped_up_usd": total_topped_up,
        "total_spent_usd": total_spent,
        "trailing_daily_burn_usd": trailing_daily_burn,
        "estimated_days_until_depleted": estimated_days_until_depleted,
        "low_balance_warning": low_balance_warning,
    }
