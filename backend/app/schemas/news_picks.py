from datetime import date, datetime

from pydantic import BaseModel


class NewsPickEvidence(BaseModel):
    title: str
    url: str
    source: str
    published_time: datetime
    sentiment: float
    importance: float
    contribution: float


class NewsPickItem(BaseModel):
    """One bullish news pick. Result fields stay None until the session has
    closed and been evaluated (spec §13) — never shown for a still-open pick."""

    rank: int
    ticker: str
    company_name: str
    news_score: float
    article_count: int
    positive_count: int
    negative_count: int
    avg_sentiment: float
    evidence: list[NewsPickEvidence]
    actual_return: float | None = None
    benchmark_return: float | None = None
    excess_return: float | None = None
    hit: bool | None = None


class NewsPickRunResponse(BaseModel):
    target_session_date: date
    generated_at: datetime
    as_of: datetime
    window_start: datetime
    candidates_scored: int
    reconstructed: bool
    benchmark_return: float | None
    hit_rate: float | None
    picks: list[NewsPickItem]


class NewsPickPerformance(BaseModel):
    window_days: int
    n_picks: int
    n_graded: int
    n_days: int
    hit_rate: float | None
    mean_actual_return: float | None
    mean_benchmark_return: float | None
    mean_excess_return: float | None


class NewsPickHistoryResponse(BaseModel):
    performance: NewsPickPerformance
    runs: list[NewsPickRunResponse]
