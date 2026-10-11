"""End-to-end coverage for spec 013 / US1 — local driver reload identity.

Scenario (per T020):

1. Stage a minimal driver directory inside the styrmin-server pod (via
   ``kubectl cp`` — the ``loadLocalApplicationDriverVersion`` mutation
   reads from the pod's filesystem).
2. Load the driver through the SDK once.  Assert exactly one
   ``ApplicationDriverVersion`` row is exposed via GraphQL for that driver.
3. Reload without touching the on-disk bytes.  Assert the row count is
   still one and the row id / ``contentHash`` are unchanged (idempotent on
   the identity tuple).
4. Edit the values template inside the pod and reload.  Assert exactly
   two rows are now exposed — same ``version`` string, two distinct
   ``contentHash`` values, both retrievable.  The original row is NOT
   deleted.
5. Replace ``spec.info.icon`` with the old ``xxxx`` placeholder and reload
   twice.  Both loads succeed and return the same row with a warning that
   names ``spec.info.icon`` (spec 020, PR #418 review item 2).

Marker policy:

* ``api_only`` — driver load is a CLI/SDK flow with no UI journey; the
  ``[ui-chromium]`` variant would re-run the same SDK call without
  exercising any UI surface (per AGENTS.md heuristic).
* ``ci`` — gates the matrix-shard pipeline.
* ``shard_general`` — the project's six valid shard markers (declared in
  ``backend/tests/e2e/conftest.py`` line 61-69) are
  ``shard_general / shard_env / shard_compute / shard_backup /
  shard_configuration``; the task spec named ``shard_readonly`` which is
  not in that set.  ``shard_general`` is the closest fit (read-heavy,
  not the env / compute / backup / configuration verticals) and is the
  one the conftest enforce_shard_markers hook will accept.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from pathlib import Path

import pytest
from styrmin_sdk import StyrminClient

from tests.e2e.conftest import PROJECT_ROOT

pytestmark = [
    pytest.mark.ci,
    pytest.mark.shard_general,
]


_FIXTURE_DRIVER_DIR = (
    PROJECT_ROOT
    / "backend"
    / "tests"
    / "unit"
    / "services"
    / "driver"
    / "fixtures"
    / "local_driver_directory"
)


def _styrmin_pod_name(kubeconfig: str) -> str:
    """Return the styrmin-server pod name in the e2e vcluster."""
    result = subprocess.run(
        [
            "kubectl",
            "--kubeconfig",
            kubeconfig,
            "-n",
            "styrmin",
            "get",
            "pods",
            "-l",
            "app.kubernetes.io/component=server,app.kubernetes.io/name=styrmin",
            "-o",
            "jsonpath={.items[0].metadata.name}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    name = result.stdout.strip()
    assert name, "styrmin-server pod not found in vcluster"
    return name


def _kubectl_exec(kubeconfig: str, pod: str, *cmd: str) -> str:
    """Run ``kubectl exec`` against the styrmin-server pod, return stdout."""
    result = subprocess.run(
        [
            "kubectl",
            "--kubeconfig",
            kubeconfig,
            "-n",
            "styrmin",
            "exec",
            pod,
            "-c",
            "styrmin-server",
            "--",
            *cmd,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def _kubectl_cp(kubeconfig: str, local: Path, pod: str, dest: str) -> None:
    """Copy ``local`` into ``<pod>:<dest>`` (recursively for directories)."""
    subprocess.run(
        [
            "kubectl",
            "--kubeconfig",
            kubeconfig,
            "-n",
            "styrmin",
            "cp",
            "-c",
            "styrmin-server",
            str(local),
            f"{pod}:{dest}",
        ],
        check=True,
    )


@pytest.mark.api_only(
    reason="Driver load is an SDK/CLI flow with no UI journey — "
    "the [ui-chromium] variant would re-run the same SDK call without "
    "exercising any UI surface."
)
async def test_local_driver_reload_creates_new_row_on_content_change(
    authenticated_styrmin_client: StyrminClient,
    vcluster: dict,
):
    """Spec 013 / US1 / T020 — local reload identity, end-to-end.

    Stages the committed local-driver fixture inside the styrmin-server
    pod (under a unique path so the test is repeatable inside one
    session), loads it, reloads it (no change), edits one file, reloads
    again, and asserts the row-set behaviour described in this module's
    docstring.
    """
    from styrmin_sdk._queries import load_query

    kubeconfig = vcluster["kubeconfig_path"]
    pod = _styrmin_pod_name(kubeconfig)

    # Stage the fixture inside the styrmin-server pod under a unique path so
    # the test is hermetic from other concurrent test data.
    pod_driver_dir = f"/tmp/driver-013-{uuid.uuid4().hex[:8]}"
    _kubectl_exec(kubeconfig, pod, "mkdir", "-p", pod_driver_dir)
    # Copy each file individually so we land them at the target prefix
    # without `kubectl cp` ambiguity around source-dir trailing slashes.
    for src_name in ("driver.styrmin.yml", "values.j2.yml", "actions.py"):
        src = _FIXTURE_DRIVER_DIR / src_name
        _kubectl_cp(
            kubeconfig,
            src,
            pod,
            f"{pod_driver_dir}/{src_name}",
        )

    client = authenticated_styrmin_client

    # ---- Step 1: first load -------------------------------------------------
    first = await client.drivers.load_local_version(pod_driver_dir)
    first_id = str(first.id)
    first_hash = first.content_hash
    first_version = first.version
    first_driver_id = str(first.application_driver_id)
    assert first_hash is not None and len(first_hash) == 64
    assert first.source_commit_sha is None  # local source

    # GraphQL exposes exactly one row.
    raw = await client._transport.execute(  # type: ignore[attr-defined]
        load_query("get_application_driver_versions"),
        {"applicationDriverId": first_driver_id},
    )
    assert "errors" not in raw, raw
    versions = raw["data"]["applicationDriver"]["versions"]
    matching = [v for v in versions if v["sourcePath"] == pod_driver_dir]
    assert len(matching) == 1, matching
    assert matching[0]["id"] == first_id
    assert matching[0]["contentHash"] == first_hash

    # ---- Step 2: reload, no file changes -> idempotent ---------------------
    second = await client.drivers.load_local_version(pod_driver_dir)
    assert str(second.id) == first_id
    assert second.content_hash == first_hash

    raw = await client._transport.execute(  # type: ignore[attr-defined]
        load_query("get_application_driver_versions"),
        {"applicationDriverId": first_driver_id},
    )
    versions = raw["data"]["applicationDriver"]["versions"]
    matching = [v for v in versions if v["sourcePath"] == pod_driver_dir]
    assert len(matching) == 1, (
        f"reload with unchanged content must not create a duplicate row; "
        f"found {len(matching)}: {matching}"
    )

    # ---- Step 3: edit the values template, reload --------------------------
    # Append a comment to the values template inside the pod. Byte-exact
    # hashing means even a trailing comment surfaces as drift.
    _kubectl_exec(
        kubeconfig,
        pod,
        "sh",
        "-c",
        f"printf '\\n# touched-{uuid.uuid4().hex[:6]}\\n' >> {pod_driver_dir}/values.j2.yml",
    )

    third = await client.drivers.load_local_version(pod_driver_dir)
    third_id = str(third.id)
    third_hash = third.content_hash
    assert third_id != first_id, "edit must produce a new row id"
    assert third_hash != first_hash, "edit must produce a new content hash"
    assert third.version == first_version, (
        "spec 013: edited driver carries the same version string; "
        "fingerprint is the disambiguator"
    )

    # Both rows are retrievable via GraphQL — the old row is NOT deleted.
    raw = await client._transport.execute(  # type: ignore[attr-defined]
        load_query("get_application_driver_versions"),
        {"applicationDriverId": first_driver_id},
    )
    versions = raw["data"]["applicationDriver"]["versions"]
    matching = [v for v in versions if v["sourcePath"] == pod_driver_dir]
    ids = {v["id"] for v in matching}
    hashes = {v["contentHash"] for v in matching}
    assert len(matching) == 2, (
        f"expected two rows after one edit, got {len(matching)}: "
        f"{json.dumps(matching, indent=2)}"
    )
    assert first_id in ids, "original row must still be present (no delete)"
    assert third_id in ids
    assert hashes == {first_hash, third_hash}

    # ---- Step 4: a placeholder icon loads, with a warning ------------------
    _kubectl_exec(
        kubeconfig,
        pod,
        "sed",
        "-i",
        "s#^    icon: .*#    icon: xxxx#",
        f"{pod_driver_dir}/driver.styrmin.yml",
    )
    icon_warning = (
        "spec.info.icon must be an absolute https URL, such as "
        "https://example.com/logo.svg (found 'xxxx'). The icon was not stored."
    )
    fourth = await client.drivers.load_local_version(pod_driver_dir)
    assert str(fourth.id) not in ids, "the edited file must produce a new row"
    assert fourth.load_warnings == [icon_warning]
    assert third.load_warnings == [], "a valid icon must load without warnings"

    # Reloading the stored file returns the same row and the same warning.
    fifth = await client.drivers.load_local_version(pod_driver_dir)
    assert str(fifth.id) == str(fourth.id)
    assert fifth.load_warnings == [icon_warning]
