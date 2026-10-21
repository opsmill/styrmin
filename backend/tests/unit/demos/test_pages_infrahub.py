"""The device list footer that the Infrahub page object waits for, and the version its About dialog shows."""

from __future__ import annotations

import pytest

from tests.e2e.demos.pages.infrahub import about_version, footer_count


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


@pytest.mark.parametrize(
    ("text", "version"),
    [
        # The rendered text of the About dialog of Infrahub 1.10.11.
        (
            "Version\nv1.10.11\nEdition\ncommunity\nDeployment ID\n18e08bca-08ce-b9d8-11ec-c51b7e07b970",
            "v1.10.11",
        ),
        ("  Version \n\n v1.11.7 \n", "v1.11.7"),
        ("Edition\ncommunity", None),
        ("Version", None),
    ],
)
def test_about_version_reads_the_line_after_version(
    text: str, version: str | None
) -> None:
    assert about_version(text) == version
