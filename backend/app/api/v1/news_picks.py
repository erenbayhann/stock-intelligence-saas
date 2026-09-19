from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.news_picks import NewsPickHistoryResponse, NewsPickRunResponse
from app.services.news_pick_service import (
    get_latest_news_picks,
    get_news_pick_history,
    news_pick_performance,
)

router = APIRouter()


@router.get("/news-picks/latest", response_model=NewsPickRunResponse)
def news_picks_latest(db: Session = Depends(get_db)):
    result = get_latest_news_picks(db)
    if result is None:
        raise HTTPException(status_code=404, detail="No news picks have been locked yet")
    return result


@router.get("/news-picks/history", response_model=NewsPickHistoryResponse)
def news_picks_history(limit: int = Query(default=7, ge=1, le=30), db: Session = Depends(get_db)):
    return {"performance": news_pick_performance(db), "runs": get_news_pick_history(db, limit=limit)}
