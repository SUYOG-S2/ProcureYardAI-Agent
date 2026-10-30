from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP


MONEY = Decimal("1")
BASE_FARE = Decimal("25")
DISTANCE_RATE = Decimal("6")
INCENTIVE = Decimal("150")
RIDER_CANCELLATION_PENALTY = Decimal("10")


@dataclass(frozen=True)
class Trip:
    trip_id: str
    rider_id: str
    service_date: date
    status: str
    distance_km: Decimal
    surge_multiplier: Decimal


def canonical_rider_id(rider_id: str) -> str:
    value = rider_id.strip().upper()
    if value.isdigit():
        return f"R{int(value):03d}"
    if value.startswith("R"):
        suffix = value[1:]
        if suffix.isdigit():
            return f"R{int(suffix):03d}"
    return value


def round_rupees(value: Decimal) -> int:
    return int(value.quantize(MONEY, rounding=ROUND_HALF_UP))


def calculate_trip_fare(trip: Trip) -> int:
    if trip.status != "completed":
        return 0
    distance_component = max(trip.distance_km - Decimal("2"), Decimal("0")) * DISTANCE_RATE
    return round_rupees((BASE_FARE + distance_component) * trip.surge_multiplier)


def calculate_expected_payout(trips: list[Trip]) -> int:
    completed_by_day: dict[date, int] = {}
    total = 0
    for trip in trips:
        if trip.status == "completed":
            total += calculate_trip_fare(trip)
            completed_by_day[trip.service_date] = completed_by_day.get(trip.service_date, 0) + 1
        elif trip.status == "cancelled_by_rider":
            total -= int(RIDER_CANCELLATION_PENALTY)
    total += sum(int(INCENTIVE) for count in completed_by_day.values() if count >= 12)
    return total


def calculate_shortfall(expected: int, actual: int) -> int:
    return max(expected - actual, 0)