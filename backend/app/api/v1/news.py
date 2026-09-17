from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.news import TopNewsResponse
from app.services.news_service import get_top_news

router = APIRouter()


@router.get("/news/top", response_model=TopNewsResponse)
def news_top(limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db)):
    return {"items": get_top_news(db, limit=limit)}
