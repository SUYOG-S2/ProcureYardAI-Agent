from __future__ import annotations

import csv
import os
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from app.payouts.calculator import Trip, canonical_rider_id


class DataStore:
    def __init__(self, data_dir: str):
        root = Path(data_dir)
        self.trips: list[Trip] = []
        self.payouts: list[dict[str, str]] = []
        with (root / "trips.csv").open(newline="") as handle:
            for row in csv.DictReader(handle):
                self.trips.append(
                    Trip(row["trip_id"], canonical_rider_id(row["rider_id"]), date.fromisoformat(row["started_at"][:10]), row["status"], Decimal(row["distance_km"]), Decimal(row["surge_multiplier"]))
                )
        with (root / "payout_lines.csv").open(newline="") as handle:
            self.payouts = list(csv.DictReader(handle))

    def rider_trips(self, rider_id: str, trip_ids: list[str] | None = None) -> list[Trip]:
        wanted = set(trip_ids or [])
        normalized = canonical_rider_id(rider_id)
        return [trip for trip in self.trips if trip.rider_id == normalized and (not wanted or trip.trip_id in wanted)]

    def trip(self, trip_id: str) -> Trip | None:
        return next((trip for trip in self.trips if trip.trip_id == trip_id), None)

    def actual_for_trips(self, rider_id: str, trips: list[Trip]) -> int:
        ids = {trip.trip_id for trip in trips}
        return sum(int(row["amount"]) for row in self.payouts if canonical_rider_id(row["rider_id"]) == canonical_rider_id(rider_id) and row["trip_id"] in ids)

    def actual_for_day(self, rider_id: str, service_date: date) -> int:
        return sum(int(row["amount"]) for row in self.payouts if canonical_rider_id(row["rider_id"]) == canonical_rider_id(rider_id) and row["payout_date"] == service_date.isoformat())