from datetime import date, timedelta

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.macro import MacroData
from app.providers.macro.fred import FREDMacroProvider, MacroObservation

# Postgres caps bind parameters at 65535; 5 columns/row means ~13000 rows/statement.
_MAX_ROWS_PER_STATEMENT = 10_000

# How far back to look for observation_dates by default.
_DEFAULT_OBSERVATION_WINDOW_DAYS = 730
# How far back to look for revision vintages of those observations — must be
# comfortably earlier than observation_start, or a series revised months
# after the fact would have its very first vintage excluded.
_VINTAGE_LOOKBACK_BUFFER_DAYS = 400


def fetch_and_store_macro(
    db: Session,
    provider: FREDMacroProvider,
    series_ids: list[str],
    observation_start: date | None = None,
    vintage_start: date | None = None,
) -> dict:
    """Pulls real point-in-time vintages (spec §3/§4) — see
    app/providers/macro/fred.py for why a wide realtime window is what makes
    this correct instead of only ever capturing "today's" vintage. Bounded
    to a configurable observation window by default (not unbounded — FRED
    returns full history back to the 1960s for some series, which would
    both be unnecessary here and blow past Postgres's bind-parameter limit
    in one statement without the chunking below).
    """
    if observation_start is None:
        observation_start = date.today() - timedelta(days=_DEFAULT_OBSERVATION_WINDOW_DAYS)
    if vintage_start is None:
        vintage_start = observation_start - timedelta(days=_VINTAGE_LOOKBACK_BUFFER_DAYS)

    observations: list[MacroObservation] = provider.get_observations_with_vintages(
        series_ids, observation_start=observation_start, vintage_start=vintage_start
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
