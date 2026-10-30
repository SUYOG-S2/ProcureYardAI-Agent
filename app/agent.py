from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any

from app.ai_clients import AIClients
from app.data import DataStore
from app.payouts.calculator import calculate_shortfall, calculate_trip_fare, canonical_rider_id
from app.payouts.payswift import PaySwiftClient, PaySwiftError
from app import storage


TRIP_ID = re.compile(r"\bT\d{6}\b", re.IGNORECASE)
RIDE_COUNT = re.compile(r"\b(?:how many|number of)\b", re.IGNORECASE)
RIDE_WORD = re.compile(r"\b(?:rides?|trips?)\b", re.IGNORECASE)
PAYMENT_WORD = re.compile(r"\b(?:payment|payout|money|paise|paisa)\b", re.IGNORECASE)
NOT_RECEIVED = re.compile(r"\b(?:not received|didn.?t receive|nahi mila|nahi aaya)\b", re.IGNORECASE)


class DisputeAgent:
    def __init__(self, data: DataStore, ai: AIClients, payswift: PaySwiftClient):
        self.data = data
        self.ai = ai
        self.payswift = payswift

    def handle(self, message_id: str, rider_id: str, text: str, received_at: str) -> str:
        rider_id = canonical_rider_id(rider_id)
        storage.trace(rider_id, "message_in", "rider_message", {"message_id": message_id, "text": text, "received_at": received_at}, None)
        if not storage.record_message(message_id, rider_id, text, received_at):
            return "Aapka message pehle hi receive ho chuka hai."

        memory_context = self.ai.recall(rider_id, text)
        storage.trace(rider_id, "tool_call", "mem0.recall", {"query": text}, memory_context)
        policy_context = self.ai.policy_context(text)
        storage.trace(rider_id, "tool_call", "pinecone.policy_context", {"query": text}, policy_context)
        context = [{"role": "user", "content": text}]
        context.extend({"role": "context", "content": str(item)} for item in memory_context)
        context.extend({"role": "policy", "content": str(item)} for item in policy_context)
        intent = self.ai.extract_intent(rider_id, text, context)
        storage.trace(rider_id, "tool_call", "openrouter.extract_intent", {"text": text}, intent)
        self.ai.remember(rider_id, [{"role": "user", "content": text}])

        if re.search(r"\b(system|ignore all previous|approve karo|999)\b", text, re.IGNORECASE):
            reply = "Main sirf aapke account ke verified payout records par madad kar sakta hoon. Kripya trip ID ya date bataiye."
            storage.add_ops_item(rider_id, "escalation", None, "Suspicious or unsupported instruction")
        else:
            reply = self._route_message(rider_id, text, received_at)

        storage.set_reply(message_id, reply)
        storage.trace(rider_id, "decision", "dispute_resolution", {"message_id": message_id}, {"reply": reply})
        storage.trace(rider_id, "reply", "rider_reply", None, reply)
        return reply

    def _route_message(self, rider_id: str, text: str, received_at: str) -> str:
        trip_ids = [value.upper() for value in TRIP_ID.findall(text)]
        service_dates = self._find_dates(text, received_at)
        service_date = service_dates[0] if service_dates else None
        if service_dates and len(service_dates) > 1 and not trip_ids:
            return self._investigate_days(rider_id, service_dates, received_at)
        if service_date and self._outside_dispute_window(service_date, received_at):
            storage.add_ops_item(rider_id, "escalation", None, f"Dispute date {service_date.isoformat()} is outside the seven-day policy window")
            return "Yeh dispute 7 din se purana hai. Ops team ko manual verification ke liye bhej diya hai."
        if not trip_ids and service_date and RIDE_COUNT.search(text) and RIDE_WORD.search(text):
            return self._count_rides(rider_id, service_date)
        if not trip_ids and service_date:
            return self._investigate_day(rider_id, service_date, received_at)
        if not trip_ids:
            return "Kaunse din ya kaunse order ka payout galat laga? Date ya order ID bata dijiye."
        payment_not_received = PAYMENT_WORD.search(text) and NOT_RECEIVED.search(text)
        return self._investigate(rider_id, trip_ids, received_at, bool(payment_not_received))

    @staticmethod
    def _find_date(text: str, received_at: str) -> date | None:
        dates = DisputeAgent._find_dates(text, received_at)
        return dates[0] if dates else None

    @staticmethod
    def _find_dates(text: str, received_at: str) -> list[date]:
        received_date = datetime.fromisoformat(received_at).date()
        if re.search(r"\bkal\b|yesterday", text, re.IGNORECASE):
            return [received_date - timedelta(days=1)]
        iso_dates = [date.fromisoformat(value) for value in re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", text)]
        if iso_dates:
            return list(dict.fromkeys(iso_dates))
        day_numbers = [int(value) for value in re.findall(r"\b(?:0?[1-9]|[12]\d|3[01])\b", text)]
        return list(dict.fromkeys(date(received_date.year, received_date.month, day) for day in day_numbers))

    def _investigate_days(self, rider_id: str, service_dates: list[date], received_at: str) -> str:
        replies = []
        for service_date in service_dates:
            if self._outside_dispute_window(service_date, received_at):
                storage.add_ops_item(rider_id, "escalation", None, f"Dispute date {service_date.isoformat()} is outside the seven-day policy window")
                replies.append(f"{service_date.strftime('%d %b')} ka case ops verification ke liye bhej diya hai.")
            else:
                replies.append(self._investigate_day(rider_id, service_date, received_at))
        return " ".join(replies)

    @staticmethod
    def _outside_dispute_window(service_date: date, received_at: str) -> bool:
        received_date = datetime.fromisoformat(received_at).date()
        age = (received_date - service_date).days
        return age < 0 or age > 7

    def _count_rides(self, rider_id: str, service_date: date) -> str:
        trips = [
            trip
            for trip in self.data.rider_trips(rider_id)
            if trip.service_date == service_date and trip.status == "completed"
        ]
        count = len(trips)
        storage.trace(
            rider_id,
            "tool_call",
            "count_completed_rides",
            {"date": service_date.isoformat()},
            {"completed_rides": count},
        )
        return f"On {service_date.strftime('%d %b %Y')}, you completed {count} rides."

    def _investigate_day(self, rider_id: str, service_date: date, received_at: str) -> str:
        trips = [trip for trip in self.data.rider_trips(rider_id) if trip.service_date == service_date]
        if not trips:
            storage.add_ops_item(rider_id, "escalation", None, "No matching trips found for the disputed date")
            return "Is date ke records verify karne ke liye ops team ko bhej diya hai."
        expected = sum(calculate_trip_fare(trip) for trip in trips)
        expected += 150 if sum(trip.status == "completed" for trip in trips) >= 12 else 0
        expected -= sum(trip.status == "cancelled_by_rider" for trip in trips) * 10
        actual = self.data.actual_for_day(rider_id, service_date)
        shortfall = calculate_shortfall(expected, actual)
        storage.trace(rider_id, "tool_call", "reconcile_day", {"date": service_date.isoformat()}, {"expected": expected, "actual": actual, "shortfall": shortfall})
        if shortfall == 0:
            return f"{service_date.strftime('%d %b')} ka payout record ke hisaab se sahi hai."
        if shortfall > 200 or self.payswift.paid_on(rider_id, datetime.fromisoformat(received_at).date()) > 0:
            storage.add_ops_item(rider_id, "approval", shortfall, "Date-based dispute exceeds auto-pay limit or is a repeat")
            return f"{service_date.strftime('%d %b')} ka verified difference ₹{shortfall} hai. Ops approval ke liye bhej diya hai."
        try:
            payment = self.payswift.create_payout(rider_id, shortfall, f"QuickDrop date dispute: {service_date.isoformat()}", f"dispute:{rider_id}:{service_date.isoformat()}")
        except PaySwiftError as error:
            storage.add_ops_item(rider_id, "escalation", shortfall, f"PaySwift payout failed for {service_date.isoformat()}: {error}")
            return f"₹{shortfall} ka verified difference mila, lekin PaySwift se payment confirm nahi ho paaya. Ops team ko bhej diya hai."
        return f"{service_date.strftime('%d %b')} ka verified difference ₹{shortfall} hai. PaySwift payment process ho gaya hai ({payment.get('payout_id', 'confirmed')})."

    def _investigate(self, rider_id: str, trip_ids: list[str], received_at: str, payment_not_received: bool = False) -> str:
        trips = [trip for trip_id in trip_ids if (trip := self.data.trip(trip_id)) is not None]
        if not trips or any(trip.rider_id != rider_id for trip in trips):
            storage.add_ops_item(rider_id, "escalation", None, "Trip is missing or does not belong to this rider")
            return "Is complaint ko verify karne ke liye ops team ko bhej diya hai."
        if any(self._outside_dispute_window(trip.service_date, received_at) for trip in trips):
            storage.add_ops_item(rider_id, "escalation", None, f"Trip dispute is outside the seven-day policy window: {', '.join(trip_ids)}")
            return "Yeh trip dispute 7 din se purana hai. Ops team ko manual verification ke liye bhej diya hai."
        expected = sum(calculate_trip_fare(trip) for trip in trips)
        actual = self.data.actual_for_trips(rider_id, trips)
        shortfall = calculate_shortfall(expected, actual)
        storage.trace(rider_id, "tool_call", "reconcile_dispute", {"trip_ids": trip_ids}, {"expected": expected, "actual": actual, "shortfall": shortfall})
        service_date = trips[0].service_date
        day_trips = [trip for trip in self.data.rider_trips(rider_id) if trip.service_date == service_date]
        completed_count = sum(trip.status == "completed" for trip in day_trips)
        case_summary = f"Trip(s): {', '.join(trip_ids)}; date: {service_date.isoformat()}; completed rides that day: {completed_count}; expected: ₹{expected}; PaySwift recorded: ₹{actual}"
        if shortfall == 0:
            if payment_not_received:
                storage.add_ops_item(rider_id, "escalation", None, f"Payment-not-received claim. {case_summary}")
                return f"Order {', '.join(trip_ids)} ke liye PaySwift record mein ₹{actual} payment dikh raha hai. Ops team ko dobara verify karne ke liye bhej diya hai."
            return f"Order {', '.join(trip_ids)} ka payout record ke hisaab se sahi hai."

        received_date = datetime.fromisoformat(received_at).date()
        if shortfall > 200 or self.payswift.paid_on(rider_id, received_date) > 0:
            storage.add_ops_item(rider_id, "approval", shortfall, f"{case_summary}; above auto-pay limit or repeat payment")
            return f"Verified difference ₹{shortfall} hai. Yeh payment ops approval ke liye bhej diya hai."
        try:
            payment = self.payswift.create_payout(rider_id, shortfall, f"QuickDrop dispute: {','.join(trip_ids)}", f"dispute:{rider_id}:{','.join(sorted(trip_ids))}")
        except PaySwiftError as error:
            storage.add_ops_item(rider_id, "escalation", shortfall, f"PaySwift payout failed for {', '.join(trip_ids)}: {error}")
            return f"₹{shortfall} ka verified difference mila, lekin PaySwift se payment confirm nahi ho paaya. Ops team ko bhej diya hai."
        return f"Order {', '.join(trip_ids)} ka verified difference ₹{shortfall} hai. PaySwift payment process ho gaya hai ({payment.get('payout_id', 'confirmed')})."