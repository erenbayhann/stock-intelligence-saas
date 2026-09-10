import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.model_version import ModelVersion
from app.services.data_quality_service import record_alert
from app.services.performance_service import compute_performance_summary

logger = logging.getLogger(__name__)

# spec §14 (added during planning): "a configurable threshold, not a
# one-time guess" — a drop of more than this many percentage points in
# trailing directional accuracy vs. the champion's own validation-time
# baseline triggers an alert. Never auto-replaces or auto-pauses the
# champion (same human-in-the-loop principle as promotion, spec §12).
DEGRADATION_THRESHOLD = 0.10
TRAILING_WINDOW = "30d"


def check_champion_performance(db: Session, job_run_id: int | None = None) -> dict:
    champion = db.scalar(select(ModelVersion).where(ModelVersion.status == "champion"))
    if champion is None:
        return {"checked": False, "reason": "no champion model_version exists"}

    baseline_accuracy = (champion.metrics or {}).get("validation", {}).get("directional_accuracy")
    if baseline_accuracy is None:
        return {"checked": False, "reason": "champion has no recorded validation-time directional_accuracy baseline"}

    trailing = compute_performance_summary(db, window=TRAILING_WINDOW, model_version_id=champion.id)
    if trailing["n_predictions"] == 0:
        return {
            "checked": True,
            "degraded": False,
            "reason": "no evaluated predictions yet for the current champion",
        }

    trailing_accuracy = trailing["directional_accuracy"]
    drop = baseline_accuracy - trailing_accuracy
    degraded = drop > DEGRADATION_THRESHOLD

    if degraded:
        record_alert(
            db,
            severity="warning",
            category="champion_performance_degraded",
            message=(
                f"Champion {champion.version_label}'s trailing {TRAILING_WINDOW} directional accuracy "
                f"({trailing_accuracy:.1%}) is {drop:.1%} below its validation-time baseline "
                f"({baseline_accuracy:.1%})"
            ),
            detail={
                "model_version_id": champion.id,
                "version_label": champion.version_label,
                "baseline_accuracy": baseline_accuracy,
                "trailing_accuracy": trailing_accuracy,
                "drop": drop,
                "threshold": DEGRADATION_THRESHOLD,
                "n_predictions": trailing["n_predictions"],
            },
            job_run_id=job_run_id,
        )

    return {
        "checked": True,
        "degraded": degraded,
        "model_version_id": champion.id,
        "baseline_accuracy": baseline_accuracy,
        "trailing_accuracy": trailing_accuracy,
        "n_predictions": trailing["n_predictions"],
    }
