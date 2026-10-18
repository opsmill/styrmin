"""``enter_text``: the E2E suite fills fields in one step, the demos type key by key."""

from __future__ import annotations

from typing import Any

from tests.e2e.pages._dom import enter_text


class _RecordingLocator:
    """Records the ``fill`` and ``press_sequentially`` calls it receives."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    async def fill(self, value: str) -> None:
        self.calls.append(("fill", (value,), {}))

    async def press_sequentially(self, text: str, *, delay: float) -> None:
        self.calls.append(("press_sequentially", (text,), {"delay": delay}))


async def test_without_delay_fills_the_text_in_one_step() -> None:
    locator = _RecordingLocator()

    await enter_text(locator, "infrahub", keystroke_delay_ms=None)  # type: ignore[arg-type]

    assert locator.calls == [("fill", ("infrahub",), {})]


async def test_with_delay_clears_the_field_then_types_each_key() -> None:
    locator = _RecordingLocator()

    await enter_text(locator, "infrahub", keystroke_delay_ms=45)  # type: ignore[arg-type]

    assert locator.calls == [
        ("fill", ("",), {}),
        ("press_sequentially", ("infrahub",), {"delay": 45}),
    ]


async def test_with_delay_and_empty_text_only_clears_the_field() -> None:
    locator = _RecordingLocator()

    await enter_text(locator, "", keystroke_delay_ms=45)  # type: ignore[arg-type]

    assert locator.calls == [("fill", ("",), {})]
