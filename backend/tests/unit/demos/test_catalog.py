"""The demo catalog's rules and the Infrahub versions file (FR-006)."""

from __future__ import annotations

import re

import pytest

from tests.e2e.demos.catalog import (
    DEMOS,
    SLUGS,
    VERSIONS_PATH,
    Demo,
    InfrahubVersions,
    check_catalog,
    load_versions,
)


async def _setup(context) -> None:
    return None


async def _record(context, state) -> None:
    return None


def _demo(slug: str, number: int, *environment_names: str) -> Demo[None]:
    return Demo(
        slug=slug,
        number=number,
        environment_names=environment_names,
        setup=_setup,
        record=_record,
    )


def test_the_committed_versions_file_is_valid() -> None:
    assert load_versions(VERSIONS_PATH) == InfrahubVersions(
        previous="1.10.11", latest="1.11.7"
    )


def test_load_versions_compares_versions_not_strings(tmp_path) -> None:
    path = tmp_path / "versions.yml"
    path.write_text('previous: "1.9.4"\nlatest: "1.10.0"\n')

    assert load_versions(path) == InfrahubVersions(previous="1.9.4", latest="1.10.0")


def test_load_versions_names_the_file_when_it_is_missing(tmp_path) -> None:
    path = tmp_path / "infrahub_versions.yml"

    with pytest.raises(ValueError) as raised:
        load_versions(path)

    assert str(raised.value) == f"{path}: the file does not exist"


@pytest.mark.parametrize(
    ("content", "problem"),
    [
        ('latest: "1.11.7"\n', "the key 'previous' is missing"),
        ('previous: "1.10.11"\n', "the key 'latest' is missing"),
        ("", "expected the keys 'previous' and 'latest'"),
        ("- 1.10.11\n", "expected the keys 'previous' and 'latest'"),
        (
            'previous: "1.11.7"\nlatest: "1.11.7"\n',
            "'latest' (1.11.7) must be greater than 'previous' (1.11.7)",
        ),
        (
            'previous: "1.11.7"\nlatest: "1.10.11"\n',
            "'latest' (1.10.11) must be greater than 'previous' (1.11.7)",
        ),
        (
            'previous: 1.10\nlatest: "1.11.7"\n',
            "the value of 'previous' must be a quoted version",
        ),
        (
            'previous: "one"\nlatest: "1.11.7"\n',
            "the value of 'previous' is not a version: 'one'",
        ),
        ("previous: [\n", "cannot read the file"),
    ],
)
def test_load_versions_names_the_file_and_the_problem(
    tmp_path, content: str, problem: str
) -> None:
    path = tmp_path / "infrahub_versions.yml"
    path.write_text(content)

    with pytest.raises(ValueError, match=rf"^{re.escape(f'{path}: {problem}')}"):
        load_versions(path)


def test_a_demo_must_use_a_prd_slug_and_its_prd_number() -> None:
    with pytest.raises(ValueError, match="Unknown demo slug 'upgrade'"):
        _demo("upgrade", 1, "lab")
    with pytest.raises(ValueError, match="has number 3, not its PRD position"):
        _demo("clone", 3, "lab")
    with pytest.raises(ValueError, match="names no environment"):
        _demo("clone", 4)


def test_check_catalog_refuses_shared_environment_names_and_wrong_order() -> None:
    upgrade = _demo("deploy-upgrade", 1, "network-lab-upgrade")
    clone = _demo("clone", 4, "network-lab-clone", "network-lab")

    check_catalog([upgrade, clone])
    with pytest.raises(ValueError, match="PRD order"):
        check_catalog([clone, upgrade])
    with pytest.raises(ValueError, match="same environment names: network-lab$"):
        check_catalog([_demo("backup-restore", 3, "network-lab"), clone])


def test_the_registered_demos_follow_the_catalog_rules() -> None:
    check_catalog(DEMOS)
    assert tuple(demo.slug for demo in DEMOS) == SLUGS
