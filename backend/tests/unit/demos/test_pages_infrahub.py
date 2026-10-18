"""The device list footer that the Infrahub page object waits for."""

from __future__ import annotations

import pytest

from tests.e2e.demos.pages.infrahub import footer_count


@pytest.mark.parametrize(
    ("text", "count"),
    [
        ("Network device\nName\nsw1\nsw1\nsw2\nsw2\n2\ncounts", 2),
        ("Network device\nName\nsw12\nsw12\n1 count", 1),
        ("Network device\nName\n2 counts\n", 2),
        ("Network device\nName\nsw2", None),
    ],
)
def test_footer_count_reads_the_number_at_the_end_of_the_list(
    text: str, count: int | None
) -> None:
    assert footer_count(text) == count
