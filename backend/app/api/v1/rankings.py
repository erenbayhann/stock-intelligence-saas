from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.rankings import RankingDetailResponse, RankingHistoryResponse, RankingResponse
from app.services.rankings_service import get_latest_ranking, get_ranking_for_date, get_ranking_history

router = APIRouter()


@router.get("/rankings/latest", response_model=RankingResponse)
def rankings_latest(db: Session = Depends(get_db)):
    result = get_latest_ranking(db)
    if result is None:
        raise HTTPException(status_code=404, detail="No final prediction snapshot exists yet")
    return result


@router.get("/rankings/history", response_model=RankingHistoryResponse)
def rankings_history(
    limit: int = Query(default=7, ge=1, le=100),
    before: date | None = None,
    db: Session = Depends(get_db),
):
    return {"items": get_ranking_history(db, limit=limit, before=before)}


@router.get("/rankings/{target_date}", response_model=RankingDetailResponse)
def rankings_for_date(target_date: date, db: Session = Depends(get_db)):
    result = get_ranking_for_date(db, target_date)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No finalized prediction for {target_date}")
    return result
