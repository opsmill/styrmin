"""The demos the record command can run, and the Infrahub versions they deploy (FR-001, FR-006)."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from packaging.version import InvalidVersion, Version

from tests.e2e.demos.scenarios import (
    backup_restore,
    clone,
    component_overrides,
    deploy_upgrade,
)
from tests.e2e.demos.semaphore_image import IMAGE as SEMAPHORE_IMAGE
from tests.e2e.demos.video import ClosingCard

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from playwright.async_api import BrowserContext, Page
    from styrmin_sdk import StyrminClient

    from tests.e2e.demos.recorder import DemoRecorder

# Every demo of the PRD, in its order. DEMOS registers one demo for each slug, in the same order.
SLUGS = ("deploy-upgrade", "component-overrides", "backup-restore", "clone")
VERSIONS_PATH = Path(__file__).with_name("infrahub_versions.yml")
VERSION_KEYS = ("previous", "latest")


@dataclass(frozen=True)
class InfrahubVersions:
    """``previous`` is the version demo 1 upgrades from; ``latest`` the version every other demo deploys."""

    previous: str
    latest: str


def load_versions(path: Path) -> InfrahubVersions:
    """Read the versions file; raise ``ValueError`` naming ``path`` when it is missing or not valid."""

    def problem(text: str) -> ValueError:
        return ValueError(f"{path}: {text}")

    try:
        content = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise problem("the file does not exist") from None
    except (OSError, yaml.YAMLError) as error:
        raise problem(f"cannot read the file: {error}") from None
    if not isinstance(content, dict):
        raise problem(f"expected the keys {' and '.join(map(repr, VERSION_KEYS))}")

    versions: dict[str, Version] = {}
    for key in VERSION_KEYS:
        if key not in content:
            raise problem(f"the key {key!r} is missing")
        value = content[key]
        if not isinstance(value, str):
            raise problem(
                f'the value of {key!r} must be a quoted version, for example "1.11.7", not {value!r}'
            )
        try:
            versions[key] = Version(value)
        except InvalidVersion:
            raise problem(f"the value of {key!r} is not a version: {value!r}") from None
    if versions["latest"] <= versions["previous"]:
        raise problem(
            f"'latest' ({content['latest']}) must be greater than 'previous' ({content['previous']})"
        )
    return InfrahubVersions(previous=content["previous"], latest=content["latest"])


@dataclass(frozen=True)
class DemoContext:
    """What a demo's setup and recorded steps act on. ``page`` is logged in to Styrmin at ``styrmin_url``."""

    client: StyrminClient
    styrmin_url: str
    browser_context: BrowserContext
    page: Page
    recorder: DemoRecorder
    versions: InfrahubVersions


@dataclass(frozen=True)
class Demo[S]:
    """One demo: ``setup`` runs before the recording starts and returns what ``record`` needs.

    ``summary`` holds the lines of the closing card; ``{previous}``, ``{latest}`` and ``{semaphore_image}``
    in them are replaced by the Infrahub versions and the demo Semaphore image. ``expected_minutes`` is how
    long a run of the demo usually takes, setup and cleanup included.
    """

    slug: str
    number: int
    title: str
    environment_names: tuple[str, ...]
    setup: Callable[[DemoContext], Awaitable[S]]
    record: Callable[[DemoContext, S], Awaitable[None]]
    summary: tuple[str, ...] = ()
    expected_minutes: int = 10
    uses_semaphore_image: bool = False

    def closing_card(self, versions: InfrahubVersions) -> ClosingCard:
        values = {
            "previous": versions.previous,
            "latest": versions.latest,
            "semaphore_image": SEMAPHORE_IMAGE,
        }
        return ClosingCard(
            self.title, tuple(line.format(**values) for line in self.summary)
        )

    def __post_init__(self) -> None:
        if self.slug not in SLUGS:
            raise ValueError(
                f"Unknown demo slug {self.slug!r}; the slugs are {', '.join(SLUGS)}"
            )
        if self.number != SLUGS.index(self.slug) + 1:
            raise ValueError(
                f"Demo {self.slug!r} has number {self.number}, not its PRD position"
            )
        if not self.environment_names:
            raise ValueError(f"Demo {self.slug!r} names no environment")


def check_catalog(demos: Sequence[Demo[Any]]) -> None:
    """Raise ``ValueError`` unless the demos are in PRD order and share no slug or environment name."""
    numbers = [demo.number for demo in demos]
    if numbers != sorted(set(numbers)):
        raise ValueError(f"The demos must be in PRD order with no repeat: {numbers}")
    # A demo deletes its environments first, so a shared name would delete another demo's kept environment.
    names = Counter(name for demo in demos for name in demo.environment_names)
    shared = sorted(name for name, count in names.items() if count > 1)
    if shared:
        raise ValueError(
            f"Two demos use the same environment names: {', '.join(shared)}"
        )


# The expected durations come from the measured runs in dev/guides/local-demo.md, rounded up.
DEMOS: tuple[Demo[Any], ...] = (
    Demo(
        slug="deploy-upgrade",
        number=1,
        title="Deploy and upgrade Infrahub",
        environment_names=(deploy_upgrade.ENVIRONMENT_NAME,),
        setup=deploy_upgrade.setup,
        record=deploy_upgrade.record,
        summary=(
            "Infrahub {previous} deployed from the Styrmin UI, then upgraded to {latest}.",
            "The upgrade ran the Infrahub driver's upgrade action: it stopped Infrahub, "
            "ran 'infrahub upgrade' and started Infrahub again.",
            "The upgrade task lists each step that it ran.",
        ),
        expected_minutes=9,
    ),
    Demo(
        slug="component-overrides",
        number=2,
        title="Override the image and the replicas of a component",
        environment_names=(component_overrides.ENVIRONMENT_NAME,),
        setup=component_overrides.setup,
        record=component_overrides.record,
        summary=(
            "The Semaphore server runs {semaphore_image}, an image that adds the Infrahub Ansible collection.",
            "Infrahub runs two server pods.",
            "Each change is an override of one component; the application driver stays the same.",
        ),
        expected_minutes=11,
        uses_semaphore_image=True,
    ),
    Demo(
        slug="backup-restore",
        number=3,
        title="Back up and restore an environment",
        environment_names=(backup_restore.ENVIRONMENT_NAME,),
        setup=backup_restore.setup,
        record=backup_restore.record,
        summary=(
            f"One backup covers Infrahub and Semaphore in the environment {backup_restore.ENVIRONMENT_NAME}.",
            "The restore brought back the device deleted in Infrahub and the task template deleted in Semaphore.",
        ),
        expected_minutes=21,
        uses_semaphore_image=True,
    ),
    Demo(
        slug="clone",
        number=4,
        title="Clone an environment",
        # The clone first, so the deletion of the environments an earlier failed run kept, and the
        # cleanup, delete it before its source.
        environment_names=(clone.CLONE_NAME, clone.ENVIRONMENT_NAME),
        setup=clone.setup,
        record=clone.record,
        summary=(
            f"{clone.CLONE_NAME} is a copy of {clone.ENVIRONMENT_NAME} with its own Infrahub and Semaphore.",
            "A device added in the clone's Infrahub shows only in the clone's Semaphore: "
            f"{len(clone.DEVICES) + 1} devices.",
            f"The Semaphore of {clone.ENVIRONMENT_NAME} still lists {len(clone.DEVICES)} devices.",
        ),
        expected_minutes=14,
        uses_semaphore_image=True,
    ),
)
check_catalog(DEMOS)
