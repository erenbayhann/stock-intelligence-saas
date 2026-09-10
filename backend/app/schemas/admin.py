from datetime import datetime

from pydantic import BaseModel


class AdminLoginRequest(BaseModel):
    password: str


class ChallengerItem(BaseModel):
    id: int
    version_label: str
    algorithm: str
    feature_set: str
    trained_at: datetime
    metrics: dict
    champion_metrics: dict | None


class JobHealthItem(BaseModel):
    job_name: str
    status: str
    started_at: datetime
    finished_at: datetime | None


class AlertItem(BaseModel):
    id: int
    severity: str
    category: str
    message: str
    detail: dict | None
    created_at: datetime
    acknowledged_at: datetime | None


class NewsRolloutProgress(BaseModel):
    eligible: bool
    trading_days_covered: int
    trading_days_required: int
    window_size: int
    coverage_pct: float
    estimated_eligible_date: str | None = None


class CreditTopupRequest(BaseModel):
    amount_usd: float
    topped_up_at: datetime
    note: str | None = None


class CreditStatus(BaseModel):
    estimated_remaining_usd: float
    total_topped_up_usd: float
    total_spent_usd: float
    trailing_daily_burn_usd: float | None
    estimated_days_until_depleted: float | None
    low_balance_warning: bool
