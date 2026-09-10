from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.performance_service import compute_performance_summary

router = APIRouter()


@router.get("/performance/summary")
def performance_summary(
    window: str = Query(default="7d", pattern="^(7d|30d|all)$"),
    db: Session = Depends(get_db),
):
    return compute_performance_summary(db, window=window)
