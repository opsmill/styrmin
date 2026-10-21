"""The environments that the record command created on a demo stack, so that it deletes only those.

A demo deletes the environments with its names before its setup (FR-009). An environment with one of those
names that the command did not create, for example one that a developer made by hand, is deleted only after
the developer confirms it. The file lives outside the repository because one demo stack serves every
checkout on the host.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from tests.e2e.demos.stack import EnvironmentRecord

FILE_NAME = "demo-environments.json"


def default_path(environ: Mapping[str, str] | None = None) -> Path:
    """Return ``$XDG_STATE_HOME/styrmin/demo-environments.json``, by default under ``~/.local/state``."""
    environ = os.environ if environ is None else environ
    state_home = environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state_home) / "styrmin" / FILE_NAME


class CreatedEnvironments:
    """The ids of the environments that the record command created on the demo stack at ``stack_url``.

    The file maps each stack URL to the ids and names of its environments. A stack created again by
    ``uv run invoke reset`` gives its environments new ids, so ids left in the file never match them.
    """

    def __init__(self, path: Path, stack_url: str) -> None:
        self._path = path
        self._stack_url = stack_url

    @property
    def path(self) -> Path:
        return self._path

    def __contains__(self, environment_id: object) -> bool:
        return environment_id in self._read().get(self._stack_url, {})

    def remember(self, environments: Iterable[EnvironmentRecord]) -> None:
        """Record ``environments`` as created by the command."""
        stacks = self._read()
        known = stacks.setdefault(self._stack_url, {})
        known.update({environment.id: environment.name for environment in environments})
        self._write(stacks)

    def forget(self, environments: Iterable[EnvironmentRecord]) -> None:
        """Remove ``environments``, which no longer exist, from the file."""
        stacks = self._read()
        known = stacks.get(self._stack_url, {})
        for environment in environments:
            known.pop(environment.id, None)
        self._write(stacks)

    def _read(self) -> dict[str, dict[str, str]]:
        try:
            content = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as error:
            raise ValueError(f"{self._path}: cannot read the file: {error}") from None
        if not isinstance(content, dict) or not all(
            isinstance(value, dict) for value in content.values()
        ):
            raise ValueError(
                f"{self._path}: expected an object of stack URLs, each with environment ids"
            )
        return content

    def _write(self, stacks: dict[str, dict[str, str]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        partial = self._path.with_name(f".{self._path.name}.partial")
        partial.write_text(
            json.dumps(stacks, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        os.replace(partial, self._path)
