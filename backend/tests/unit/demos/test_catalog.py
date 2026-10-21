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
from tests.e2e.demos.recorder import ACTION_MS, SLOW_ACTION_MS


async def _setup(context) -> None:
    return None


async def _record(context, state) -> None:
    return None


def _demo(
    slug: str, number: int, *environment_names: str, hands_over: tuple[str, ...] = ()
) -> Demo[None]:
    return Demo(
        slug=slug,
        number=number,
        title=f"Title of {slug}",
        environment_names=environment_names,
        setup=_setup,
        record=_record,
        hands_over=hands_over,
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


def test_a_demo_must_use_a_known_slug_and_its_position_in_the_run_order() -> None:
    with pytest.raises(ValueError, match="Unknown demo slug 'upgrade'"):
        _demo("upgrade", 1, "lab")
    with pytest.raises(
        ValueError, match="has number 3, not its position in the run order"
    ):
        _demo("clone", 3, "lab")
    with pytest.raises(ValueError, match="names no environment"):
        _demo("clone", 4)
    # A demo that only hands over an environment names one.
    assert _demo("setup", 0, hands_over=("lab",)).all_environment_names == ("lab",)


def test_check_catalog_refuses_shared_environment_names_and_wrong_order() -> None:
    upgrade = _demo("deploy-upgrade", 1, "network-lab-upgrade")
    clone = _demo("clone", 4, "network-lab-clone", "network-lab")

    check_catalog([upgrade, clone])
    with pytest.raises(ValueError, match="run order"):
        check_catalog([clone, upgrade])
    with pytest.raises(ValueError, match="same environment names: network-lab$"):
        check_catalog([_demo("backup-restore", 3, "network-lab"), clone])


def test_check_catalog_refuses_an_environment_handed_over_to_no_later_demo() -> None:
    setup = _demo("setup", 0, hands_over=("network-lab-upgrade",))
    upgrade = _demo("deploy-upgrade", 1, "network-lab-upgrade")

    check_catalog([setup, upgrade])
    with pytest.raises(
        ValueError,
        match="'setup' hands over environments that no later demo names: network-lab-upgrade$",
    ):
        check_catalog([setup, _demo("clone", 4, "network-lab")])


def test_the_registered_demos_follow_the_catalog_rules() -> None:
    check_catalog(DEMOS)
    assert tuple(demo.slug for demo in DEMOS) == SLUGS
    assert [demo.number for demo in DEMOS] == [0, 1, 2, 3, 4]


def test_the_setup_demo_sets_up_the_stack_and_hands_its_environment_to_demo_1() -> None:
    setup, upgrade, *others = DEMOS

    assert (setup.slug, setup.sets_up_stack) == ("setup", True)
    assert setup.environment_names == ()
    assert setup.hands_over == upgrade.environment_names == ("network-lab-upgrade",)
    assert not any(demo.sets_up_stack for demo in (upgrade, *others))


def test_the_setup_demo_and_demo_1_act_twice_as_slowly_as_the_others() -> None:
    assert SLOW_ACTION_MS == 2 * ACTION_MS
    assert [demo.action_ms for demo in DEMOS] == [
        SLOW_ACTION_MS,
        SLOW_ACTION_MS,
        ACTION_MS,
        ACTION_MS,
        ACTION_MS,
    ]


def test_each_demo_has_a_closing_card_with_the_versions_filled_in() -> None:
    versions = InfrahubVersions(previous="1.10.11", latest="1.11.7")

    cards = {demo.slug: demo.closing_card(versions) for demo in DEMOS}

    assert cards["deploy-upgrade"].title == "Deploy and upgrade Infrahub"
    assert cards["deploy-upgrade"].lines[0] == (
        "Infrahub 1.10.11 deployed from the Styrmin UI, then upgraded to 1.11.7."
    )
    assert "About dialog shows 1.11.7" in cards["deploy-upgrade"].lines[2]
    assert cards["setup"].title == "Set up Styrmin"
    assert "network-lab-upgrade" in cards["setup"].lines[2]
    assert "styrmin-demo/semaphore:v2.16.47" in cards["component-overrides"].lines[0]
    for card in cards.values():
        assert card.title
        assert card.lines
        assert not any("{" in line for line in card.lines)


def test_each_demo_gives_how_long_a_run_usually_takes() -> None:
    assert [demo.expected_minutes for demo in DEMOS] == [3, 11, 11, 21, 14]
    assert [demo.uses_semaphore_image for demo in DEMOS] == [
        False,
        False,
        True,
        True,
        True,
    ]
