"""CLI entrypoint: python -m app.jobs.train_challengers

Measurement-only run answering spec §9's "gradient boosting if it earns its
complexity" question: trains XGBoost/LightGBM in both regression mode and
ranking mode (rank:ndcg / lambdarank, since the product's real objective is
a daily ranking, not a point regression) against the same historical
dataset and split the current champion was trained on. Persists each as a
model_versions row with status='challenger' — never touches the current
champion, never auto-promotes anything (spec §12: promotion is always a
human decision). Prints a comparison table against the reigning champion.
"""

import logging
from datetime import date, timedelta

from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionLocal
from app.ml.challengers import ALL_CHALLENGER_ALGORITHMS, train_challengers
from app.models.model_version import ModelVersion
from app.services.job_run_service import track_job_run
from app.services.universe_service import load_constituents

logger = logging.getLogger(__name__)

JOB_NAME = "challenger_experiment"


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    end_date = date.today()
    start_date = end_date - timedelta(days=settings.historical_dataset_days)
    universe_tickers = {row["ticker"] for row in load_constituents()}

    db = SessionLocal()
    try:
        with track_job_run(db, JOB_NAME) as job_run:
            results = train_challengers(db, start_date, end_date, universe_tickers, ALL_CHALLENGER_ALGORITHMS)

            champion = db.scalar(select(ModelVersion).where(ModelVersion.status == "champion"))
            champion_summary = (
                {
                    "version_label": champion.version_label,
                    "algorithm": champion.algorithm,
                    "test_mean_rank_ic": (champion.metrics or {}).get("test", {}).get("mean_rank_ic"),
                    "test_precision_at_5": (champion.metrics or {}).get("test", {}).get("precision_at_5"),
                }
                if champion
                else None
            )

            job_run.job_metadata = {"champion": champion_summary, "challengers": results}
            result = job_run.job_metadata
    finally:
        db.close()

    logger.info("Done: %s", result)


if __name__ == "__main__":
    main()
