"""Build the demo Semaphore image that demos 2 to 4 deploy (FR-015); it is never pushed to a registry."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

BUILD_DIR = Path(__file__).with_name("semaphore")
DOCKERFILE = BUILD_DIR / "Dockerfile"
REPOSITORY = "styrmin-demo/semaphore"
OUTPUT_LINES = 20
_FROM_PATTERN = re.compile(
    r"^FROM semaphoreui/semaphore:v(\S+?)@sha256:[0-9a-f]{64}$", re.MULTILINE
)


class ImageBuildError(RuntimeError):
    """docker is missing, or ``docker build`` failed."""


def read_version(dockerfile: Path = DOCKERFILE) -> str:
    """Return the Semaphore version of the Dockerfile's digest-pinned ``FROM`` line."""
    match = _FROM_PATTERN.search(dockerfile.read_text(encoding="utf-8"))
    if match is None:
        raise ValueError(
            f"{dockerfile} has no line 'FROM semaphoreui/semaphore:v<version>@sha256:<digest>'"
        )
    return match.group(1)


# The `semaphore` driver deploys `<docker_image>:v<version>`, so the demos deploy this version with
# `docker_image` set to REPOSITORY.
SEMAPHORE_VERSION = read_version()
IMAGE = f"{REPOSITORY}:v{SEMAPHORE_VERSION}"


def build_arguments(*, no_cache: bool) -> list[str]:
    """Return the ``docker`` arguments that build ``IMAGE``; Docker reuses its cached layers unless ``no_cache``."""
    return [
        "build",
        *(["--no-cache"] if no_cache else []),
        "--tag",
        IMAGE,
        str(BUILD_DIR),
    ]


def build(*, no_cache: bool = False) -> None:
    """Build ``IMAGE``; raise ``ImageBuildError`` with the last lines of the output when the build fails.

    The build runs every time, so a changed Dockerfile or playbook reaches the image; when nothing changed,
    Docker reuses its cached layers and the build takes a few seconds.
    """
    executable = shutil.which("docker")
    if executable is None:
        raise ImageBuildError("docker is not on the PATH")
    result = subprocess.run(
        [executable, *build_arguments(no_cache=no_cache)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        output = result.stdout.splitlines() + result.stderr.splitlines()
        tail = "\n".join(output[-OUTPUT_LINES:])
        raise ImageBuildError(
            f"docker build of {IMAGE} exited with code {result.returncode}:\n{tail}"
        )
