from datetime import datetime

from pydantic import BaseModel


class TopNewsItem(BaseModel):
    """A single (article, company) pairing, not a prediction — the LLM's own
    relevance/importance/sentiment judgment for one headline, independent of
    the price_fundamentals_macro ranking model (spec §12 excludes news from
    that model's feature set until spec §15's coverage bar is met).
    """

    ticker: str
    company_name: str
    title: str
    url: str
    source: str
    published_time: datetime
    sentiment: float | None
    event_category: str | None
    importance: float
    score: float
    # Realized outcome, populated once the reacting session has actually
    # closed (time-based, not tab-based — an article can already have a
    # closed reacting session in /news/top too). Both returns shown directly
    # side by side rather than a pre-computed excess/difference.
    actual_return: float | None = None
    benchmark_return: float | None = None
    direction_correct: bool | None = None


class TopNewsResponse(BaseModel):
    items: list[TopNewsItem]


class NewsHistoryDay(BaseModel):
    date: str
    items: list[TopNewsItem]


class NewsHistoryResponse(BaseModel):
    days: list[NewsHistoryDay]


class NewsStats(BaseModel):
    total_classified: int
    graded: int
    accuracy_pct: float | None
