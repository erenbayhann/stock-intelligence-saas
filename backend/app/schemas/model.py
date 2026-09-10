from datetime import datetime

from pydantic import BaseModel


class ModelVersionSummary(BaseModel):
    id: int
    version_label: str
    algorithm: str
    feature_set: str
    status: str
    trained_at: datetime
    promoted_at: datetime | None
    headline_metrics: dict


class ModelVersionListResponse(BaseModel):
    versions: list[ModelVersionSummary]


class ModelVersionDetailResponse(BaseModel):
    id: int
    version_label: str
    algorithm: str
    feature_set: str
    status: str
    trained_at: datetime
    promoted_at: datetime | None
    hyperparameters: dict
    metrics: dict
    training_run: dict | None
