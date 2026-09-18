from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.news import NewsHistoryResponse, TopNewsResponse
from app.services.news_service import get_news_history, get_top_news

router = APIRouter()


@router.get("/news/top", response_model=TopNewsResponse)
def news_top(limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db)):
    return {"items": get_top_news(db, limit=limit)}


@router.get("/news/history", response_model=NewsHistoryResponse)
def news_history(days: int = Query(default=7, ge=1, le=30), db: Session = Depends(get_db)):
    return {"days": get_news_history(db, days=days)}
