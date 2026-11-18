"""Compare two sets of Helm values as values, not as text (specs/032-styrmin-driver-cli, FR-011)."""

import difflib

import yaml


def normalised_yaml(values: object) -> str:
    """The values written in one fixed format: sorted keys, block style."""
    return yaml.safe_dump(values, sort_keys=True, default_flow_style=False)


def compare_values(base: object, rendered: object, *, base_label: str, rendered_label: str) -> list[str]:
    """The unified diff between two sets of values, or an empty list when they are equal.

    Both sides are written in the same format first, so a different key order, indentation
    or quoting is not a difference. A different type is: ``"8080"`` and ``8080`` differ.
    """
    before = normalised_yaml(base).splitlines(keepends=True)
    after = normalised_yaml(rendered).splitlines(keepends=True)
    return list(difflib.unified_diff(before, after, fromfile=base_label, tofile=rendered_label))
