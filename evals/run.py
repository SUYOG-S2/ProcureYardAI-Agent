from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


@dataclass
class ScenarioResult:
    name: str
    checks: list[tuple[str, bool, str]]

    @property
    def passed(self) -> bool:
        return all(check[1] for check in self.checks)


def payout_total(client: httpx.Client, payswift_url: str, rider_id: str) -> int:
    response = client.get(f"{payswift_url.rstrip('/')}/v1/payouts", params={"rider_id": rider_id})
    response.raise_for_status()
    payload: Any = response.json()
    payouts = payload if isinstance(payload, list) else payload.get("payouts", [])
    return sum(int(item.get("amount", 0)) for item in payouts)


def expected_approval(expected: dict[str, Any]) -> int:
    if "approval" in expected and expected["approval"] is not None:
        return int(expected["approval"])
    return sum(int(item.get("approval", 0)) for item in expected.get("one_of", []))


def run_scenario(client: httpx.Client, base_url: str, payswift_url: str, scenario: dict[str, Any]) -> ScenarioResult:
    expected = scenario["expected"]
    rider_id = scenario["rider_id"]
    before_paid = payout_total(client, payswift_url, rider_id)
    before_pending = client.get(f"{base_url}/ops/pending").json()
    replies: list[str] = []
    response_ok = True
    for turn in scenario["turns"]:
        if turn["from"] != "rider":
            continue
        response = client.post(
            f"{base_url}/messages",
            json={"message_id": turn["message_id"], "rider_id": rider_id, "text": turn["text"], "received_at": turn["received_at"]},
        )
        response_ok = response_ok and response.is_success
        if response.is_success:
            replies.append(response.json().get("reply", ""))

    after_paid = payout_total(client, payswift_url, rider_id)
    pending = client.get(f"{base_url}/ops/pending").json()
    trace = client.get(f"{base_url}/trace/{rider_id}").json()
    observed_approval = sum(int(item.get("amount") or 0) for item in pending if item.get("rider_id") == rider_id and item.get("type") == "approval") - sum(int(item.get("amount") or 0) for item in before_pending if item.get("rider_id") == rider_id and item.get("type") == "approval")
    text = " ".join(replies).lower()
    mentions = expected.get("reply_mentions", [])
    allowed_outcomes = expected.get("one_of", [expected])
    outcome_ok = any(
        after_paid - before_paid == int(item.get("payout", 0))
        and observed_approval == int(item.get("approval", 0) or 0)
        for item in allowed_outcomes
    )
    checks = [
        ("HTTP response", response_ok, "all rider messages returned 2xx"),
        ("financial outcome", outcome_ok, f"paid delta={after_paid - before_paid}, approval delta={observed_approval}"),
        ("reply facts", all(str(mention).lower() in text for mention in mentions), f"required={mentions}"),
        ("trace completeness", bool(trace) and any(item.get("type") == "message_in" for item in trace) and any(item.get("type") == "reply" for item in trace), "message and reply trace events exist"),
    ]
    return ScenarioResult(scenario["scenario"], checks)


def main() -> int:
    if len(sys.argv) not in {2, 3}:
        print("usage: python evals/run.py SERVICE_URL [PAYSWIFT_URL]")
        return 2
    base_url = sys.argv[1].rstrip("/")
    payswift_url = (sys.argv[2] if len(sys.argv) == 3 else os.getenv("PAYSWIFT_BASE_URL", "http://localhost:8081")).rstrip("/")
    scenarios = json.loads((Path(__file__).parents[1] / "data" / "conversations.json").read_text())
    results: list[ScenarioResult] = []
    with httpx.Client(timeout=20) as client:
        for scenario in scenarios:
            try:
                results.append(run_scenario(client, base_url, payswift_url, scenario))
            except Exception as error:
                results.append(ScenarioResult(scenario["scenario"], [("scenario execution", False, str(error))]))
    for result in results:
        print(f"{'PASS' if result.passed else 'FAIL'}: {result.name}")
        for name, passed, detail in result.checks:
            print(f"  {'ok' if passed else '!!'} {name}: {detail}")
    passed = sum(result.passed for result in results)
    print(f"\nEvaluation score: {passed}/{len(results)} scenarios passed")
    print("Method: deterministic rubric plus PaySwift black-box reconciliation and trace inspection; no LLM judge is used for financial decisions.")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())