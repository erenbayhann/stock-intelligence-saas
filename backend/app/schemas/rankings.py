from datetime import date, datetime

from pydantic import BaseModel


class NewsRef(BaseModel):
    id: int
    title: str
    url: str
    source: str
    published_time: datetime


class RankingItem(BaseModel):
    """spec §1/§15: never a raw predicted %, only AI Score/Confidence/Rank."""

    rank: int
    ticker: str
    company_name: str
    ai_score: float
    confidence: str
    explanation: str
    related_news: list[NewsRef] = []


class RankingItemWithResult(RankingItem):
    """Only ever populated for a PAST, already-closed session (spec §13)."""

    actual_return: float | None = None
    benchmark_return: float | None = None
    vs_benchmark: float | None = None
    direction_correct: bool | None = None


class RankingResponse(BaseModel):
    generated_at: datetime
    model_version: str
    top5: list[RankingItem]


class RankingDetailResponse(BaseModel):
    target_session_date: date
    generated_at: datetime
    model_version: str
    benchmark_return: float | None
    hit_rate: float | None
    top5: list[RankingItemWithResult]
    notable_news: list[NewsRef] = []


class RankingHistoryTopPick(BaseModel):
    ticker: str
    ai_score: float
    actual_return: float | None = None
    vs_benchmark: float | None = None
    direction_correct: bool | None = None


class RankingHistoryItem(BaseModel):
    target_session_date: date
    hit_rate: float | None
    mean_excess_return: float | None
    top_pick: RankingHistoryTopPick | None = None


class RankingHistoryResponse(BaseModel):
    items: list[RankingHistoryItem]
