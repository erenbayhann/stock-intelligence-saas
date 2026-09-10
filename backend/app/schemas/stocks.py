from datetime import date, datetime

from pydantic import BaseModel


class FundamentalsSummary(BaseModel):
    period_end: date
    eps: float | None
    pe_ratio: float | None
    revenue_growth: float | None
    operating_margin: float | None
    market_cap: float | None
    dividend_yield: float | None


class StockDetailResponse(BaseModel):
    ticker: str
    company_name: str
    sector: str | None
    current_rank: int | None = None
    ai_score: float | None = None
    confidence: str | None = None
    explanation: str | None = None
    latest_fundamentals: FundamentalsSummary | None = None


class PriceBar(BaseModel):
    ts: datetime
    session_type: str
    open: float
    high: float
    low: float
    close: float
    volume: int


class StockPricesResponse(BaseModel):
    ticker: str
    bars: list[PriceBar]


class NewsItem(BaseModel):
    id: int
    title: str
    url: str
    source: str
    published_time: datetime
    sentiment: float | None
    event_category: str | None


class StockNewsResponse(BaseModel):
    ticker: str
    articles: list[NewsItem]


class StockPredictionItem(BaseModel):
    target_session_date: date
    rank: int
    ai_score: float
    confidence: str
    actual_return: float | None = None
    vs_benchmark: float | None = None
    direction_correct: bool | None = None


class StockPredictionsResponse(BaseModel):
    ticker: str
    predictions: list[StockPredictionItem]
