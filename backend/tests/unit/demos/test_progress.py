"""The lines that the record command prints while it waits."""

from __future__ import annotations

import asyncio

from tests.e2e.demos.progress import waiting


async def test_a_wait_prints_when_it_starts_while_it_lasts_and_when_it_ends(
    capsys,
) -> None:
    async with waiting("the namespaces are gone", limit=600.0, every=0.02):
        await asyncio.sleep(0.07)

    lines = [line.split("  ", 1)[1] for line in capsys.readouterr().out.splitlines()]
    assert lines[0] == "Waiting: the namespaces are gone (at most 10 min)"
    assert lines[1].startswith("Still waiting after ")
    assert lines[-1] == "Done after 0 s: the namespaces are gone"
    assert len(lines) >= 4


async def test_a_wait_that_raises_prints_no_end_line_and_stops_its_heartbeat(
    capsys,
) -> None:
    try:
        async with waiting("Infrahub runs", every=0.01):
            raise RuntimeError("failed")
    except RuntimeError:
        pass
    await asyncio.sleep(0.05)

    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == 1
    assert lines[0].endswith("Waiting: Infrahub runs")
