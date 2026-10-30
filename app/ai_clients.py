from __future__ import annotations

import json
from typing import Any

import httpx
from mem0 import MemoryClient
from pinecone import Pinecone


class AIClients:
    def __init__(self, settings: Any):
        self.settings = settings
        self.memory = MemoryClient(api_key=settings.mem0_api_key)
        self.pinecone = Pinecone(api_key=settings.pinecone_api_key)
        try:
            self.index = self.pinecone.Index(settings.pinecone_index_name)
        except Exception:
            self.index = None

    def recall(self, rider_id: str, query: str) -> list[dict[str, Any]]:
        try:
            result = self.memory.search(query, user_id=rider_id, limit=5)
        except Exception:
            return []
        return result if isinstance(result, list) else []

    def extract_intent(self, rider_id: str, text: str, context: list[dict[str, str]]) -> dict[str, Any]:
        prompt = {
            "rider_id": rider_id,
            "message": text,
            "context": context,
            "schema": {"intent": "string", "trip_ids": "array", "dates": "array", "language": "string", "confidence": "number"},
        }
        response = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={"Authorization": f"Bearer {self.settings.openrouter_api_key}"},
            json={"model": self.settings.openrouter_model, "messages": [{"role": "system", "content": "Return only valid JSON. Extract entities; never decide money or payments."}, {"role": "user", "content": str(prompt)}], "response_format": {"type": "json_object"}},
            timeout=8.0,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        return json.loads(content) if isinstance(content, str) else content

    def remember(self, rider_id: str, messages: list[dict[str, str]]) -> None:
        self.memory.add(messages, user_id=rider_id)

    def policy_context(self, _query: str) -> list[dict[str, Any]]:
        if self.index is None:
            return []
        try:
            result = self.index.query(vector=[0.0] * 1536, top_k=3, include_metadata=True, filter={"text": {"$exists": True}})
        except Exception:
            return []
        return [match.metadata for match in result.matches if match.metadata]