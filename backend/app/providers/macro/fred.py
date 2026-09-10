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

    Point-in-time vintages, done correctly: pass a WIDE realtime_start/
    realtime_end query window (rather than the default, which is today/today
    and only returns the current vintage — the bug this replaced). FRED's
    default output_type=1 then returns one row per (observation_date,
    vintage) pair actually observed within that window, each carrying its
    own real realtime_start/realtime_end — e.g. CPIAUCSL for Jan 2024 comes
    back as three separate rows (first published 2024-02-13, revised
    2025-02-12, revised again 2026-02-13), each with the correct value for
    that vintage. This was verified against the live API before relying on
    it: an earlier attempt used output_type=2, whose response is a dynamic
    `{series_id}_{vintage_date}` column per vintage — real but needlessly
    complex parsing next to this documented, standard approach.
    """

    def __init__(self, api_key: str, timeout: float = 30.0) -> None:
        if not api_key:
            raise ValueError("FRED API key must not be empty")
        self._api_key = api_key
        self._timeout = timeout

    def get_observations_with_vintages(
        self,
        series_ids: list[str],
        observation_start: date,
        vintage_start: date,
    ) -> list[MacroObservation]:
        """observation_start bounds which observation_dates are returned;
        vintage_start bounds how far back into revision history to look —
        pass something safely earlier than observation_start (a series
        revised months after the fact would otherwise have its earliest
        vintage excluded).
        """
        today = date.today()
        observations: list[MacroObservation] = []
        with httpx.Client(timeout=self._timeout) as client:
            for series_id in series_ids:
                params = {
                    "series_id": series_id,
                    "api_key": self._api_key,
                    "file_type": "json",
                    "sort_order": "asc",
                    "observation_start": observation_start.isoformat(),
                    "realtime_start": vintage_start.isoformat(),
                    "realtime_end": today.isoformat(),
                }

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
                            realtime_start=date.fromisoformat(obs["realtime_start"]),
                            realtime_end=date.fromisoformat(obs["realtime_end"]),
                        )
                    )
        return observations
