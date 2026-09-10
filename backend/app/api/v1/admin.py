from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import ADMIN_COOKIE_NAME, create_admin_session_token, require_admin, verify_admin_password
from app.db.session import get_db
from app.models.data_quality_alert import DataQualityAlert
from app.models.job_run import JobRun
from app.models.model_version import ModelVersion
from app.schemas.admin import (
    AdminLoginRequest,
    CreditStatus,
    CreditTopupRequest,
    NewsRolloutProgress,
)
from app.services.admin_service import credit_status, news_rollout_progress, record_credit_topup

router = APIRouter()


@router.post("/admin/login")
def admin_login(body: AdminLoginRequest, response: Response, settings: Settings = Depends(get_settings)):
    if not verify_admin_password(body.password, settings):
        raise HTTPException(status_code=401, detail="Invalid admin password")

    token = create_admin_session_token(settings)
    response.set_cookie(
        key=ADMIN_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=settings.app_env != "development",
        samesite="lax",
        max_age=settings.admin_session_ttl_minutes * 60,
    )
    return {"status": "ok"}


@router.get("/admin/challengers/pending", dependencies=[Depends(require_admin)])
def admin_challengers_pending(db: Session = Depends(get_db)):
    champion = db.scalar(select(ModelVersion).where(ModelVersion.status == "champion"))
    challengers = db.scalars(
        select(ModelVersion).where(ModelVersion.status == "challenger").order_by(ModelVersion.trained_at.desc())
    ).all()
    return {
        "champion_metrics": (champion.metrics or {}) if champion else None,
        "challengers": [
            {
                "id": c.id,
                "version_label": c.version_label,
                "algorithm": c.algorithm,
                "feature_set": c.feature_set,
                "trained_at": c.trained_at,
                "metrics": c.metrics or {},
            }
            for c in challengers
        ],
    }


@router.post("/admin/challengers/{model_version_id}/approve", dependencies=[Depends(require_admin)])
def admin_approve_challenger(model_version_id: int, db: Session = Depends(get_db)):
    challenger = db.get(ModelVersion, model_version_id)
    if challenger is None or challenger.status != "challenger":
        raise HTTPException(status_code=404, detail="No pending challenger with that id")

    current_champion = db.scalar(select(ModelVersion).where(ModelVersion.status == "champion"))
    if current_champion is not None:
        current_champion.status = "retired"
        current_champion.promoted_at = None

    challenger.status = "champion"
    challenger.promoted_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "ok", "new_champion_id": challenger.id}


@router.post("/admin/challengers/{model_version_id}/reject", dependencies=[Depends(require_admin)])
def admin_reject_challenger(model_version_id: int, db: Session = Depends(get_db)):
    challenger = db.get(ModelVersion, model_version_id)
    if challenger is None or challenger.status != "challenger":
        raise HTTPException(status_code=404, detail="No pending challenger with that id")

    challenger.status = "retired"
    db.commit()
    return {"status": "ok"}


@router.get("/admin/jobs", dependencies=[Depends(require_admin)])
def admin_jobs(db: Session = Depends(get_db)):
    latest_per_job = select(JobRun).distinct(JobRun.job_name).order_by(JobRun.job_name, JobRun.started_at.desc())
    rows = db.scalars(latest_per_job).all()
    return {
        "jobs": [
            {"job_name": j.job_name, "status": j.status, "started_at": j.started_at, "finished_at": j.finished_at}
            for j in rows
        ]
    }


@router.get("/admin/alerts", dependencies=[Depends(require_admin)])
def admin_alerts(
    limit: int = Query(default=50, ge=1, le=500),
    unacknowledged_only: bool = False,
    db: Session = Depends(get_db),
):
    query = select(DataQualityAlert).order_by(DataQualityAlert.created_at.desc()).limit(limit)
    if unacknowledged_only:
        query = query.where(DataQualityAlert.acknowledged_at.is_(None))
    rows = db.scalars(query).all()
    return {
        "alerts": [
            {
                "id": a.id, "severity": a.severity, "category": a.category, "message": a.message,
                "detail": a.detail, "created_at": a.created_at, "acknowledged_at": a.acknowledged_at,
            }
            for a in rows
        ]
    }


@router.post("/admin/alerts/{alert_id}/acknowledge", dependencies=[Depends(require_admin)])
def admin_acknowledge_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = db.get(DataQualityAlert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Unknown alert id")
    alert.acknowledged_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "ok"}


@router.get("/admin/news-rollout-progress", response_model=NewsRolloutProgress, dependencies=[Depends(require_admin)])
def admin_news_rollout_progress(db: Session = Depends(get_db)):
    return news_rollout_progress(db)


@router.post("/admin/credit-topups", dependencies=[Depends(require_admin)])
def admin_credit_topups(body: CreditTopupRequest, db: Session = Depends(get_db)):
    topup = record_credit_topup(db, body.amount_usd, body.topped_up_at, body.note)
    return {"status": "ok", "id": topup.id}


@router.get("/admin/credit-status", response_model=CreditStatus, dependencies=[Depends(require_admin)])
def admin_credit_status(db: Session = Depends(get_db)):
    return credit_status(db)
