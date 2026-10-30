from datetime import date
from decimal import Decimal

import pytest

from app.payouts.calculator import (
    Trip,
    calculate_expected_payout,
    calculate_shortfall,
    calculate_trip_fare,
    canonical_rider_id,
    round_rupees,
)


def trip(status="completed", distance="6", surge="1.5"):
    return Trip("T000001", "R001", date(2026, 9, 20), status, Decimal(distance), Decimal(surge))


def test_trip_fare_uses_half_up_rounding_and_surge():
    assert calculate_trip_fare(trip()) == 74


def test_rider_cancellation_is_a_negative_line():
    assert calculate_expected_payout([trip("cancelled_by_rider")]) == -10


def test_incentive_requires_twelve_completed_trips():
    assert calculate_expected_payout([trip() for _ in range(12)]) == 12 * 74 + 150


def test_incentive_is_calculated_per_calendar_day():
    first_day = [trip() for _ in range(11)]
    second_day = [Trip(f"T{i:06d}", "R001", date(2026, 9, 21), "completed", Decimal("6"), Decimal("1.5")) for i in range(12)]
    assert calculate_expected_payout(first_day + second_day) == (11 * 74) + (12 * 74) + 150


def test_non_completed_trips_do_not_earn_trip_fare():
    assert calculate_trip_fare(trip("cancelled_by_customer")) == 0
    assert calculate_trip_fare(trip("cancelled_by_rider")) == 0


def test_half_up_rounding_handles_exact_half():
    assert round_rupees(Decimal("10.5")) == 11
    assert round_rupees(Decimal("11.5")) == 12


def test_shortfall_never_becomes_negative():
    assert calculate_shortfall(100, 120) == 0
    assert calculate_shortfall(120, 100) == 20


def test_rider_ids_are_normalized_for_export_variants():
    assert canonical_rider_id("r7") == "R007"
    assert canonical_rider_id("003") == "R003"
    assert canonical_rider_id(" R019 ") == "R019"
    assert canonical_rider_id("unknown") == "UNKNOWN"


@pytest.mark.parametrize(
    ("distance", "surge", "expected"),
    [
        ("0", "1", 25),
        ("1.9", "1", 25),
        ("2", "1", 25),
        ("2.1", "1", 26),
        ("3", "1", 31),
        ("5", "1", 43),
        ("10", "1", 73),
        ("2", "1.2", 30),
        ("5", "1.2", 52),
        ("5", "1.5", 65),
        ("7.5", "1.5", 87),
        ("11.2", "1.5", 120),
    ],
)
def test_trip_fare_policy_examples(distance, surge, expected):
    assert calculate_trip_fare(trip(distance=distance, surge=surge)) == expected


@pytest.mark.parametrize(
    ("rider_id", "expected"),
    [
        ("r1", "R001"),
        ("R1", "R001"),
        ("r01", "R001"),
        ("R01", "R001"),
        ("r7", "R007"),
        ("R7", "R007"),
        ("r040", "R040"),
        ("  r19  ", "R019"),
    ],
)
def test_canonical_rider_id_variants(rider_id, expected):
    assert canonical_rider_id(rider_id) == expected


@pytest.mark.parametrize(
    ("expected", "actual", "shortfall"),
    [
        (0, 0, 0),
        (1, 0, 1),
        (100, 0, 100),
        (200, 50, 150),
        (200, 200, 0),
        (200, 201, 0),
        (1000, 250, 750),
    ],
)
def test_shortfall_examples(expected, actual, shortfall):
    assert calculate_shortfall(expected, actual) == shortfall