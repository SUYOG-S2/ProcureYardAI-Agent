from datetime import date

from app.data import DataStore
from app.agent import DisputeAgent


def test_data_store_normalizes_rider_ids_and_reads_authoritative_exports():
    store = DataStore("data")

    trips = store.rider_trips("R007", ["T840677"])

    assert len(trips) == 1
    assert trips[0].rider_id == "R007"
    assert store.actual_for_trips("r7", trips) == 67


def test_data_store_aggregates_all_payout_lines_for_a_day():
    store = DataStore("data")

    amount = store.actual_for_day("R003", date(2026, 9, 20))

    assert amount == 371


def test_data_store_returns_empty_for_unknown_rider():
    assert DataStore("data").rider_trips("R999") == []


def test_data_store_returns_none_for_unknown_trip():
    assert DataStore("data").trip("T999999") is None


def test_data_store_filters_trips_by_requested_ids():
    trips = DataStore("data").rider_trips("R003", ["T926334"])

    assert [trip.trip_id for trip in trips] == ["T926334"]


def test_dispute_window_allows_last_seven_days_only():
    assert not DisputeAgent._outside_dispute_window(date(2026, 9, 15), "2026-09-22T09:00:00+05:30")
    assert DisputeAgent._outside_dispute_window(date(2026, 9, 14), "2026-09-22T09:00:00+05:30")


def test_data_store_does_not_match_another_riders_trip():
    assert DataStore("data").rider_trips("R003", ["T840677"]) == []


def test_data_store_trip_lookup_preserves_trip_attributes():
    trip = DataStore("data").trip("T926334")

    assert trip is not None
    assert trip.rider_id == "R003"
    assert str(trip.distance_km) == "6.0"
    assert str(trip.surge_multiplier) == "1.5"