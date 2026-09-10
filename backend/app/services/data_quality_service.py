import logging

from sqlalchemy.orm import Session

from app.models.data_quality_alert import DataQualityAlert

logger = logging.getLogger(__name__)


def record_alert(
    db: Session,
    *,
    severity: str,
    category: str,
    message: str,
    detail: dict | None = None,
    job_run_id: int | None = None,
) -> DataQualityAlert:
    """Logs a data-quality alert (spec §25) — a job succeeding with one of
    these logged is the normal pattern for a provider-level or per-row failure
    (e.g. an FMP 402 for one ticker, or one article's LLM extraction failing,
    spec §5), not a job failure in itself.
    """
    alert = DataQualityAlert(
        job_run_id=job_run_id,
        severity=severity,
        category=category,
        message=message,
        detail=detail,
    )
    db.add(alert)
    db.commit()
    logger.warning("data_quality_alert[%s/%s]: %s", severity, category, message)
    return alert
