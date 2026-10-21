"""The demo Semaphore image: one place for its version, and the docker build (FR-015)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from tests.e2e.demos import semaphore_image
from tests.e2e.demos.semaphore_image import (
    DOCKERFILE,
    IMAGE,
    SEMAPHORE_VERSION,
    ImageBuildError,
    build,
    build_arguments,
    read_version,
)

REPOSITORY_ROOT = Path(semaphore_image.__file__).parents[4]


def test_the_version_comes_from_the_digest_pinned_from_line() -> None:
    assert SEMAPHORE_VERSION == "2.16.47"
    assert IMAGE == "styrmin-demo/semaphore:v2.16.47"
    assert DOCKERFILE.read_text().count("FROM semaphoreui/semaphore:v") == 1


def test_the_version_is_the_semaphore_drivers_default_version() -> None:
    driver = yaml.safe_load(
        (REPOSITORY_ROOT / "driver/examples/semaphore/driver.styrmin.yml").read_text()
    )

    assert driver["spec"]["default_version"] == SEMAPHORE_VERSION


def test_the_dockerfile_pins_an_exact_infrahub_sdk_version() -> None:
    assert "'infrahub-sdk==" in DOCKERFILE.read_text()


@pytest.mark.parametrize(
    "line",
    [
        "FROM semaphoreui/semaphore:v2.16.47",
        "FROM semaphoreui/semaphore:latest@sha256:" + "a" * 64,
    ],
)
def test_read_version_refuses_a_from_line_without_a_version_and_a_digest(
    tmp_path, line: str
) -> None:
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text(f"{line}\nUSER root\n")

    with pytest.raises(ValueError, match="has no line 'FROM semaphoreui/semaphore"):
        read_version(dockerfile)


def test_build_arguments_tag_the_image_and_skip_the_cache_only_when_asked() -> None:
    directory = str(DOCKERFILE.parent)

    assert build_arguments(no_cache=False) == ["build", "--tag", IMAGE, directory]
    assert build_arguments(no_cache=True) == [
        *("build", "--no-cache", "--tag", IMAGE, directory)
    ]


def test_build_names_the_last_lines_of_a_failed_build(monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")
    output = "\n".join(f"line {number}" for number in range(30))
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(
            returncode=1, stdout=output, stderr="ERROR: pull access denied"
        ),
    )

    with pytest.raises(ImageBuildError) as raised:
        build()

    message = str(raised.value)
    assert message.startswith(f"docker build of {IMAGE} exited with code 1:\n")
    assert "line 29\nERROR: pull access denied" in message
    assert "line 10\n" not in message


def test_build_needs_docker(monkeypatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)

    with pytest.raises(ImageBuildError, match="docker is not on the PATH"):
        build()
