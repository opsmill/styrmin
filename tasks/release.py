"""Release-related Invoke tasks (changelog assembly via towncrier)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from invoke.collection import Collection
from invoke.tasks import task

from .utils import MAIN_DIRECTORY_PATH, print_header

if TYPE_CHECKING:
    from invoke.context import Context

ns = Collection()


@task
def draft(context: Context, version: str = "Unreleased") -> None:
    """Render the pending news fragments without consuming them.

    Unlike infrahub, towncrier cannot infer the version from an importable
    package here, so one is always passed explicitly.
    """
    print_header(f"Rendering pending news fragments as {version}...")
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(f"towncrier build --draft --version {version}", pty=True)


@task(name="build-changelog")
def build_changelog(context: Context, version: str) -> None:
    """Assemble the news fragments into CHANGELOG.md and delete them.

    The release workflow runs this on `develop`; run it locally only to
    reproduce a release build.
    """
    print_header(f"Building CHANGELOG.md for {version}...")
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(f"towncrier build --yes --version {version}", pty=True)


ns.add_task(draft)
ns.add_task(build_changelog)
