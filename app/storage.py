from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg


SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    message_id TEXT PRIMARY KEY,
    rider_id TEXT NOT NULL,
    text TEXT NOT NULL,
    received_at TEXT NOT NULL,
    reply TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS trace_events (
    id BIGSERIAL PRIMARY KEY,
    rider_id TEXT NOT NULL,
    at TIMESTAMPTZ NOT NULL DEFAULT now(),
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    input JSONB,
    output JSONB
);
CREATE TABLE IF NOT EXISTS ops_items (
    id UUID PRIMARY KEY,
    rider_id TEXT NOT NULL,
    type TEXT NOT NULL,
    amount INTEGER,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    decision_at TIMESTAMPTZ
);
"""


def database_url() -> str:
    value = os.environ.get("DATABASE_URL")
    if not value:
        raise RuntimeError("DATABASE_URL is required")
    return value


def connect() -> psycopg.Connection:
    return psycopg.connect(database_url(), autocommit=True)


def init_db() -> None:
    with connect() as connection:
        connection.execute(SCHEMA)


def record_message(message_id: str, rider_id: str, text: str, received_at: str) -> bool:
    with connect() as connection:
        result = connection.execute(
            """INSERT INTO messages(message_id, rider_id, text, received_at)
               VALUES (%s, %s, %s, %s) ON CONFLICT (message_id) DO NOTHING""",
            (message_id, rider_id, text, received_at),
        )
        return result.rowcount == 1


def set_reply(message_id: str, reply: str) -> None:
    with connect() as connection:
        connection.execute("UPDATE messages SET reply = %s WHERE message_id = %s", (reply, message_id))


def trace(rider_id: str, event_type: str, name: str, input_data: Any, output_data: Any) -> None:
    with connect() as connection:
        connection.execute(
            "INSERT INTO trace_events(rider_id, type, name, input, output) VALUES (%s, %s, %s, %s, %s)",
            (rider_id, event_type, name, json.dumps(input_data), json.dumps(output_data)),
        )


def get_trace(rider_id: str) -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT at, type, name, input, output FROM trace_events WHERE rider_id = %s ORDER BY id",
            (rider_id,),
        ).fetchall()
    return [{"at": row[0].isoformat(), "type": row[1], "name": row[2], "input": row[3], "output": row[4]} for row in rows]


def get_riders_with_activity() -> list[str]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT DISTINCT rider_id FROM trace_events ORDER BY rider_id"
        ).fetchall()
    return [row[0] for row in rows]


def add_ops_item(rider_id: str, item_type: str, amount: int | None, reason: str) -> str:
    item_id = str(uuid.uuid4())
    with connect() as connection:
        connection.execute(
            "INSERT INTO ops_items(id, rider_id, type, amount, reason) VALUES (%s, %s, %s, %s, %s)",
            (item_id, rider_id, item_type, amount, reason),
        )
    return item_id


def pending_ops() -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT id, rider_id, type, amount, reason, created_at FROM ops_items WHERE status = 'pending' ORDER BY created_at"
        ).fetchall()
    return [{"id": str(row[0]), "rider_id": row[1], "type": row[2], "amount": row[3], "reason": row[4], "created_at": row[5].isoformat()} for row in rows]


def decide_ops_item(item_id: str, decision: str) -> bool:
    with connect() as connection:
        result = connection.execute(
            "UPDATE ops_items SET status = %s, decision_at = %s WHERE id = %s AND status = 'pending'",
            (decision, datetime.now(timezone.utc), item_id),
        )
    return result.rowcount == 1


def get_ops_item(item_id: str) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute("SELECT id, rider_id, type, amount, reason FROM ops_items WHERE id = %s AND status = 'pending'", (item_id,)).fetchone()
    if not row:
        return None
    return {"id": str(row[0]), "rider_id": row[1], "type": row[2], "amount": row[3], "reason": row[4]}