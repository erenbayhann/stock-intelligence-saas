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
    # Realized outcome — only ever populated in /news/history (a past,
    # already-closed reacting session); always None in /news/top, mirroring
    # spec §13's rule that a live/current view never shows result fields.
    actual_return: float | None = None
    vs_benchmark: float | None = None
    direction_correct: bool | None = None


class TopNewsResponse(BaseModel):
    items: list[TopNewsItem]


class NewsHistoryDay(BaseModel):
    date: str
    items: list[TopNewsItem]


class NewsHistoryResponse(BaseModel):
    days: list[NewsHistoryDay]
