from datetime import date

from sqlalchemy import select

from app.models.macro import MacroData
from app.providers.macro.fred import MacroObservation
from app.services.macro_service import fetch_and_store_macro


class FakeFREDProvider:
    def __init__(self, observations: list[MacroObservation]):
        self._observations = observations

    def get_observations_with_vintages(self, series_ids, observation_start, vintage_start):
        return self._observations


def test_fetch_and_store_macro_persists_real_vintage_fields(db_session):
    observations = [
        MacroObservation("CPIAUCSL", date(2024, 1, 1), 309.685, date(2024, 2, 13), date(2025, 2, 11)),
        MacroObservation("CPIAUCSL", date(2024, 1, 1), 309.794, date(2025, 2, 12), date(2026, 2, 12)),
    ]
    provider = FakeFREDProvider(observations)

    result = fetch_and_store_macro(db_session, provider, ["CPIAUCSL"])

    assert result["observations_written"] == 2
    rows = db_session.scalars(
        select(MacroData).where(MacroData.series_id == "CPIAUCSL").order_by(MacroData.realtime_start)
    ).all()
    assert len(rows) == 2
    assert rows[0].realtime_start == date(2024, 2, 13)
    assert float(rows[0].value) == 309.685
    assert rows[1].realtime_start == date(2025, 2, 12)
    assert float(rows[1].value) == 309.794


def test_point_in_time_query_picks_the_vintage_known_at_as_of(db_session):
    """The whole point of storing multiple vintages: a query as_of a date
    before a revision must see the ORIGINAL value, never the revised one.
    """
    observations = [
        MacroObservation("CPIAUCSL", date(2024, 1, 1), 309.685, date(2024, 2, 13), date(2025, 2, 11)),
        MacroObservation("CPIAUCSL", date(2024, 1, 1), 309.794, date(2025, 2, 12), date(2026, 2, 12)),
    ]
    fetch_and_store_macro(db_session, FakeFREDProvider(observations), ["CPIAUCSL"])

    from datetime import datetime, timezone

    from app.services.feature_service import compute_macro_features

    as_of_before_revision = datetime(2024, 6, 1, tzinfo=timezone.utc)
    features = compute_macro_features(db_session, as_of_before_revision)
    assert features["macro_cpiaucsl"] == 309.685  # NOT the 2025 revision

    as_of_after_revision = datetime(2025, 6, 1, tzinfo=timezone.utc)
    features_after = compute_macro_features(db_session, as_of_after_revision)
    assert features_after["macro_cpiaucsl"] == 309.794


def test_fetch_and_store_macro_upsert_updates_realtime_end(db_session):
    provider_v1 = FakeFREDProvider([
        MacroObservation("DGS10", date(2024, 1, 2), 4.0, date(2024, 1, 3), date(9999, 12, 31)),
    ])
    fetch_and_store_macro(db_session, provider_v1, ["DGS10"])

    provider_v2 = FakeFREDProvider([
        MacroObservation("DGS10", date(2024, 1, 2), 4.0, date(2024, 1, 3), date(2024, 1, 10)),
    ])
    fetch_and_store_macro(db_session, provider_v2, ["DGS10"])

    rows = db_session.scalars(select(MacroData).where(MacroData.series_id == "DGS10")).all()
    assert len(rows) == 1
    assert rows[0].realtime_end == date(2024, 1, 10)
