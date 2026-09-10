import logging
from dataclasses import dataclass
from datetime import date

import httpx

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

# A small, fixed, interpretable set of macro series (spec §8) — Treasury
# yields, Fed funds rate, inflation, unemployment, volatility. Extending this
# list later is a config change, not a rewrite.
DEFAULT_SERIES = [
    "DGS10",  # 10-Year Treasury yield
    "DGS2",  # 2-Year Treasury yield
    "FEDFUNDS",  # Effective federal funds rate
    "CPIAUCSL",  # CPI, all urban consumers
    "UNRATE",  # Unemployment rate
    "VIXCLS",  # CBOE Volatility Index
]


@dataclass(frozen=True)
class MacroObservation:
    series_id: str
    observation_date: date
    value: float
    realtime_start: date
    realtime_end: date


class FREDMacroProvider:
    """FRED (spec §4, MacroDataProvider) — real API, free key.

    Point-in-time note: this pulls each series' *current* vintage (FRED's
    default `output_type=1`) and stamps every row with today as
    `realtime_start` — correct for live/prospective use (a feature snapshot
    built today only ever sees rows whose realtime_start <= today, which is
    exactly what was just ingested). It is NOT a full historical-vintage
    backfill: FRED's true revision history requires `output_type=2`, whose
    response shape is a dynamic `{series_id}_{vintage_date}` column per
    vintage rather than a fixed `value` field, and reconstructing exact
    historical realtime windows from it is real added complexity deferred to
    Phase 4 (historical dataset construction), where backtesting rigor
    actually depends on it. Series like Treasury yields/Fed funds are never
    revised in practice, so this gap mainly affects CPIAUCSL/UNRATE.
    """

    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        if not api_key:
            raise ValueError("FRED API key must not be empty")
        self._api_key = api_key
        self._timeout = timeout

    def get_latest_observations(
        self, series_ids: list[str], observation_start: date | None = None
    ) -> list[MacroObservation]:
        today = date.today()
        observations: list[MacroObservation] = []
        with httpx.Client(timeout=self._timeout) as client:
            for series_id in series_ids:
                params = {
                    "series_id": series_id,
                    "api_key": self._api_key,
                    "file_type": "json",
                    "sort_order": "asc",
                }
                if observation_start:
                    params["observation_start"] = observation_start.isoformat()

                response = client.get(_BASE_URL, params=params)
                response.raise_for_status()
                payload = response.json()

                for obs in payload.get("observations", []):
                    if obs["value"] == ".":  # FRED's own "no data" marker
                        continue
                    observations.append(
                        MacroObservation(
                            series_id=series_id,
                            observation_date=date.fromisoformat(obs["date"]),
                            value=float(obs["value"]),
                            realtime_start=today,
                            realtime_end=date(9999, 12, 31),
                        )
                    )
        return observations
