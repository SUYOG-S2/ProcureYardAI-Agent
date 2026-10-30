from datetime import date
from typing import Any

import httpx


class PaySwiftError(RuntimeError):
    pass


class PaySwiftClient:
    def __init__(self, base_url: str, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        self.client = client or httpx.Client(timeout=8.0)

    def list_payouts(self, rider_id: str) -> list[dict[str, Any]]:
        response = self.client.get(f"{self.base_url}/v1/payouts", params={"rider_id": rider_id})
        if response.status_code >= 400:
            raise PaySwiftError(f"PaySwift payout lookup failed: {response.status_code}")
        payload = response.json()
        return payload if isinstance(payload, list) else payload.get("payouts", [])

    def paid_on(self, rider_id: str, payout_date: date) -> int:
        total = 0
        for payout in self.list_payouts(rider_id):
            created_at = str(payout.get("created_at", payout.get("date", "")))
            if created_at.startswith(payout_date.isoformat()):
                total += int(payout.get("amount", 0))
        return total

    def create_payout(self, rider_id: str, amount: int, reference: str, idempotency_key: str) -> dict[str, Any]:
        response = self.client.post(
            f"{self.base_url}/v1/payouts",
            headers={"Idempotency-Key": idempotency_key},
            json={"rider_id": rider_id, "amount": amount, "reference": reference},
        )
        if response.status_code >= 400:
            raise PaySwiftError(f"PaySwift payout failed: {response.status_code}")
        return response.json()