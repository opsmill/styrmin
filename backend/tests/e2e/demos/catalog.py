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
    component_overrides,
    deploy_upgrade,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from playwright.async_api import BrowserContext, Page
    from styrmin_sdk import StyrminClient

    from tests.e2e.demos.recorder import DemoRecorder

# Every demo of the PRD, in its order. A slug is in DEMOS only once its scenario exists.
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
    """One demo: ``setup`` runs before the recording starts and returns what ``record`` needs."""

    slug: str
    number: int
    environment_names: tuple[str, ...]
    setup: Callable[[DemoContext], Awaitable[S]]
    record: Callable[[DemoContext, S], Awaitable[None]]

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


DEMOS: tuple[Demo[Any], ...] = (
    Demo(
        slug="deploy-upgrade",
        number=1,
        environment_names=(deploy_upgrade.ENVIRONMENT_NAME,),
        setup=deploy_upgrade.setup,
        record=deploy_upgrade.record,
    ),
    Demo(
        slug="component-overrides",
        number=2,
        environment_names=(component_overrides.ENVIRONMENT_NAME,),
        setup=component_overrides.setup,
        record=component_overrides.record,
    ),
    Demo(
        slug="backup-restore",
        number=3,
        environment_names=(backup_restore.ENVIRONMENT_NAME,),
        setup=backup_restore.setup,
        record=backup_restore.record,
    ),
)
check_catalog(DEMOS)
