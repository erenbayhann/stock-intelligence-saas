from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.stocks import (
    StockDetailResponse,
    StockNewsResponse,
    StockPredictionsResponse,
    StockPricesResponse,
)
from app.services.stocks_service import (
    get_stock_detail,
    get_stock_news,
    get_stock_predictions,
    get_stock_prices,
)

router = APIRouter()


@router.get("/stocks/{ticker}", response_model=StockDetailResponse)
def stock_detail(ticker: str, db: Session = Depends(get_db)):
    result = get_stock_detail(db, ticker)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown ticker: {ticker}")
    return result


@router.get("/stocks/{ticker}/prices", response_model=StockPricesResponse)
def stock_prices(
    ticker: str,
    from_: date | None = Query(default=None, alias="from"),
    to: date | None = None,
    session: str = Query(default="regular", pattern="^(regular|pre|after|all)$"),
    db: Session = Depends(get_db),
):
    result = get_stock_prices(db, ticker, from_date=from_, to_date=to, session=session)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown ticker: {ticker}")
    return result


@router.get("/stocks/{ticker}/news", response_model=StockNewsResponse)
def stock_news(ticker: str, limit: int = Query(default=20, ge=1, le=100), db: Session = Depends(get_db)):
    result = get_stock_news(db, ticker, limit=limit)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown ticker: {ticker}")
    return result


@router.get("/stocks/{ticker}/predictions", response_model=StockPredictionsResponse)
def stock_predictions(ticker: str, limit: int = Query(default=30, ge=1, le=200), db: Session = Depends(get_db)):
    result = get_stock_predictions(db, ticker, limit=limit)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown ticker: {ticker}")
    return result
