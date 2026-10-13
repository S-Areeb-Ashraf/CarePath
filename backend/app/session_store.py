"""Persistent, per-patient chat history.

Chat is stored in Supabase (table: patient_chat_history) keyed by
patient_reference, so messages survive sign-out / sign-in and browser
changes. `clear_chat` deletes ONLY the messages; appointments, slots and
all appointment-system side effects are untouched.

The in-memory fallback keeps unit tests and offline use working without
any extra packages.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from .config import Settings

try:
    from supabase import create_client  # type: ignore
except Exception:  # supabase not installed or not configured
    create_client = None

_TABLE = "patient_chat_history"


class ChatHistoryStore:
    def __init__(self, settings: Settings, repo: Any | None = None):
        self._repo = repo
        self._available = False
        self._memory: dict[str, list[dict[str, Any]]] = {}
        if create_client and settings.supabase_url and settings.supabase_service_role_key:
            try:
                self._client = create_client(settings.supabase_url, settings.supabase_service_role_key)
                self._available = True
            except Exception:
                pass

    # ---------- internal ----------
    def _backends(self):
        if self._available:
            yield self._client
        yield None  # memory fallback

    def _load(self, patient_reference: str) -> list[dict[str, Any]]:
        if self._available:
            try:
                row = (
                    self._client.table(_TABLE)
                    .select("messages")
                    .eq("patient_reference", patient_reference)
                    .limit(1)
                    .execute()
                )
                rows = getattr(row, "data", None) or []
                if rows:
                    messages = rows[0].get("messages")
                    if isinstance(messages, list):
                        return messages
            except Exception:
                pass
        return self._memory.get(patient_reference, [])

    def _persist(self, patient_reference: str, messages: list[dict[str, Any]]) -> None:
        if self._available:
            try:
                self._client.table(_TABLE).upsert(
                    {"patient_reference": patient_reference, "messages": messages},
                    on_conflict="patient_reference",
                ).execute()
                return
            except Exception:
                pass
        self._memory[patient_reference] = messages

    # ---------- public API ----------
    def get(self, patient_reference: str) -> list[dict[str, Any]]:
        return self._load(patient_reference)

    def append(self, patient_reference: str, user_message: str, assistant_message: str) -> None:
        messages = self._load(patient_reference)
        messages = messages[-40:]  # keep the last 40 messages (20 exchanges)
        messages.append({"role": "user", "content": user_message})
        messages.append({"role": "assistant", "content": assistant_message})
        self._persist(patient_reference, messages)

    def clear(self, patient_reference: str) -> None:
        self._persist(patient_reference, [])


def make_session_id() -> UUID:
    from uuid import uuid4

    return uuid4()
