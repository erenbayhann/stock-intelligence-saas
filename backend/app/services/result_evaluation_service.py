import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.prediction import Prediction, PredictionResult, PredictionRun
from app.services.label_service import compute_realized_label

logger = logging.getLogger(__name__)


def evaluate_pending_predictions(db: Session) -> dict:
    """spec §13: after a predicted session closes, compute and store the
    realized outcome for every prediction that doesn't have one yet.

    A prediction is only evaluated once a real close-to-close bar exists for
    both the stock and the benchmark on its target_session_date — never
    fabricates a result for a still-open session (compute_realized_label
    already enforces this: it returns None when the data isn't there,
    spec §27). prediction_results rows are written once and never updated,
    mirroring predictions' own immutability (spec §11).
    """
    pending = db.execute(
        select(Prediction.id, Prediction.security_id, Prediction.raw_predicted_excess_return, PredictionRun.target_session_date)
        .join(PredictionRun, Prediction.prediction_run_id == PredictionRun.id)
        .outerjoin(PredictionResult, PredictionResult.prediction_id == Prediction.id)
        .where(PredictionResult.id.is_(None))
    ).all()

    evaluated = 0
    not_yet_closed = 0

    for prediction_id, security_id, raw_predicted_excess_return, target_session_date in pending:
        label = compute_realized_label(db, security_id, target_session_date)
        if label is None:
            not_yet_closed += 1
            continue

        predicted = float(raw_predicted_excess_return)
        prediction_error = predicted - label["actual_excess_return"]
        direction_correct = (predicted > 0) == (label["actual_excess_return"] > 0)

        db.add(
            PredictionResult(
                prediction_id=prediction_id,
                actual_return=label["actual_return"],
                benchmark_return=label["benchmark_return"],
                actual_excess_return=label["actual_excess_return"],
                prediction_error=prediction_error,
                direction_correct=direction_correct,
                evaluated_at=datetime.now(timezone.utc),
            )
        )
        evaluated += 1

    db.commit()
    logger.info("evaluate_pending_predictions: %d evaluated, %d not yet closed", evaluated, not_yet_closed)
    return {"evaluated": evaluated, "not_yet_closed": not_yet_closed}
