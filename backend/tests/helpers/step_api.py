"""A fake ``recordStep`` API for tests that run the real flow step reporter."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest

from styrmin_backend.agent.steps import reporter as reporter_module


class FakeStepApi:
    """Answers ``recordStep`` with one id per step key and logs ``(event, key)`` into ``events``."""

    def __init__(self, events: list[tuple[Any, ...]]) -> None:
        self.events = events
        self.ids: dict[str, UUID] = {}
        self.records: list[dict] = []

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Route the reporter's HTTP calls to this fake."""
        real_client = httpx.AsyncClient
        monkeypatch.setattr(
            reporter_module,
            "httpx",
            SimpleNamespace(
                AsyncClient=lambda **kwargs: real_client(
                    transport=httpx.MockTransport(self.handle), **kwargs
                )
            ),
        )

    def handle(self, request: httpx.Request) -> httpx.Response:
        record = json.loads(request.content)["variables"]["input"]
        self.records.append(record)
        if "stepId" in record:
            key = next(k for k, v in self.ids.items() if str(v) == record["stepId"])
        else:
            key = record["key"]
            self.ids.setdefault(key, uuid4())
        self.events.append((record["event"], key))
        return httpx.Response(
            200,
            json={"data": {"recordStep": {"id": str(self.ids[key]), "status": "x"}}},
        )

    def started(self, key: str) -> dict:
        return next(
            r for r in self.records if r["event"] == "STARTED" and r.get("key") == key
        )

    def failed(self, key: str) -> dict:
        return next(
            r
            for r in self.records
            if r["event"] == "FAILED" and r.get("stepId") == str(self.ids[key])
        )
