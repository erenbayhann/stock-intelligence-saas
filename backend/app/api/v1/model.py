from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.model_version import ModelVersion
from app.models.training_run import TrainingRun
from app.schemas.model import ModelVersionDetailResponse, ModelVersionListResponse

router = APIRouter()


@router.get("/model/versions", response_model=ModelVersionListResponse)
def model_versions(db: Session = Depends(get_db)):
    rows = db.scalars(select(ModelVersion).order_by(ModelVersion.trained_at.desc())).all()
    return {
        "versions": [
            {
                "id": mv.id,
                "version_label": mv.version_label,
                "algorithm": mv.algorithm,
                "feature_set": mv.feature_set,
                "status": mv.status,
                "trained_at": mv.trained_at,
                "promoted_at": mv.promoted_at,
                "headline_metrics": (mv.metrics or {}).get("test", {}),
            }
            for mv in rows
        ]
    }


@router.get("/model/versions/{model_version_id}", response_model=ModelVersionDetailResponse)
def model_version_detail(model_version_id: int, db: Session = Depends(get_db)):
    mv = db.get(ModelVersion, model_version_id)
    if mv is None:
        raise HTTPException(status_code=404, detail=f"Unknown model_version id: {model_version_id}")

    training_run = db.scalar(
        select(TrainingRun).where(TrainingRun.resulting_model_version_id == mv.id)
    )
    return {
        "id": mv.id,
        "version_label": mv.version_label,
        "algorithm": mv.algorithm,
        "feature_set": mv.feature_set,
        "status": mv.status,
        "trained_at": mv.trained_at,
        "promoted_at": mv.promoted_at,
        "hyperparameters": mv.hyperparameters or {},
        "metrics": mv.metrics or {},
        "training_run": (
            {
                "train_window": [training_run.train_window_start, training_run.train_window_end],
                "validation_window": [training_run.validation_window_start, training_run.validation_window_end],
                "test_window": [training_run.test_window_start, training_run.test_window_end],
                "status": training_run.status,
                "notes": training_run.notes,
            }
            if training_run
            else None
        ),
    }
