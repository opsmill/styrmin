"""T102: audit-trail coverage for scheduling field changes.

Verifies that the existing ``compute_context_diff`` machinery naturally
reports nested ``scheduling`` field changes (runtime_class, resource
requests, tolerations, affinity blocks). The recursive ``_diff_dicts``
helper already handles nested dicts and scalar replacement — this test
locks in that behaviour so future timeline changes don't silently lose
scheduling audit coverage.
"""

from __future__ import annotations

from styrmin_backend.services.deployment_timeline import compute_context_diff


def test_scheduling_scalar_change_surfaces_in_diff() -> None:
    prev = {
        "deployment": {
            "config": {"scheduling": {"runtime_class": "kata"}},
        }
    }
    curr = {
        "deployment": {
            "config": {"scheduling": {"runtime_class": "gvisor"}},
        }
    }

    diff = compute_context_diff(prev, curr)
    paths = [(c.path, c.action) for c in diff.changes]
    assert (
        "deployment.config.scheduling.runtime_class",
        "modified",
    ) in paths


def test_scheduling_resource_field_added_surfaces_in_diff() -> None:
    prev = {"scheduling": {}}
    curr = {
        "scheduling": {"resources": {"requests": {"cpu": "100m", "memory": "256Mi"}}}
    }

    diff = compute_context_diff(prev, curr)
    paths = {c.path: c.action for c in diff.changes}
    assert paths["scheduling.resources"] == "added"


def test_scheduling_cleared_surfaces_as_removed() -> None:
    prev = {"scheduling": {"runtime_class": "kata"}}
    curr: dict = {"scheduling": {}}

    diff = compute_context_diff(prev, curr)
    paths = {c.path: c.action for c in diff.changes}
    assert paths["scheduling.runtime_class"] == "removed"


def test_tolerations_list_replacement_surfaces_modified() -> None:
    prev = {
        "scheduling": {
            "tolerations": [{"key": "dedicated", "operator": "Equal", "value": "batch"}]
        }
    }
    curr = {
        "scheduling": {
            "tolerations": [{"key": "dedicated", "operator": "Equal", "value": "gpu"}]
        }
    }

    diff = compute_context_diff(prev, curr)
    paths = {c.path: c.action for c in diff.changes}
    # Lists are replaced wholesale by _diff_dicts (they don't recurse
    # into sibling-indexed items) — modification surfaces at the list
    # path itself.
    assert paths["scheduling.tolerations"] == "modified"
