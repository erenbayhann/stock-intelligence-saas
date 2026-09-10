from datetime import date, timedelta

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.macro import MacroData
from app.providers.macro.fred import FREDMacroProvider, MacroObservation

# Postgres caps bind parameters at 65535; 5 columns/row means ~13000 rows/statement.
_MAX_ROWS_PER_STATEMENT = 10_000


def fetch_and_store_macro(
    db: Session,
    provider: FREDMacroProvider,
    series_ids: list[str],
    observation_start: date | None = None,
) -> dict:
    """Bounds to the trailing ~2 years by default — this job is for keeping
    recent/live macro data current, not a full historical backfill (FRED
    returns full history back to the 1960s for some series if unbounded,
    which is both unnecessary here and would blow past Postgres's
    bind-parameter limit in one statement). A true historical vintage
    backfill is Phase 4's concern (see app/providers/macro/fred.py).
    """
    if observation_start is None:
        observation_start = date.today() - timedelta(days=730)

    observations: list[MacroObservation] = provider.get_latest_observations(
        series_ids, observation_start=observation_start
    )
    if not observations:
        return {"observations_written": 0}

    rows = [
        {
            "series_id": o.series_id,
            "observation_date": o.observation_date,
            "value": o.value,
            "realtime_start": o.realtime_start,
            "realtime_end": o.realtime_end,
            "source": "fred",
        }
        for o in observations
    ]

    written = 0
    for i in range(0, len(rows), _MAX_ROWS_PER_STATEMENT):
        chunk = rows[i : i + _MAX_ROWS_PER_STATEMENT]
        stmt = insert(MacroData).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["series_id", "observation_date", "realtime_start"],
            set_={"value": stmt.excluded.value, "realtime_end": stmt.excluded.realtime_end},
        )
        db.execute(stmt)
        written += len(chunk)
    db.commit()
    return {"observations_written": written}
