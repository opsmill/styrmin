# Driver reload identity — provenance fingerprint

Closes [opsmill/styrmin#262](https://github.com/opsmill/styrmin/issues/262).

## Summary

Application Driver Versions are now identified by a **provenance
fingerprint** in addition to their `spec.version` string. Local drivers
are fingerprinted by a SHA-256 content hash over three canonical files
(`driver.styrmin.yml`, the values template, and `actions.py` when
`spec.actions` is non-empty); git drivers are fingerprinted by the
resolved HEAD commit SHA.

This unlocks the iteration loop the issue called out:

- Editing any of the three hashed files and reloading creates a new
  `ApplicationDriverVersion` row — no need to bump `spec.version`.
- Reloading byte-identical content is now a true no-op (no row, no
  cascade `IntegrityError`).
- Every UI / CLI / SDK surface renders driver-version labels as
  `<version>@<short>` (7 hex chars); detail surfaces show the full
  hash/SHA with a copy-to-clipboard control.

The new GraphQL fields on `ApplicationDriverVersion` are `contentHash`
and `sourceCommitSha` — exactly one is non-null per row, discriminated
by `sourceType`.

## What changed (high level)

- **Backend**: two nullable columns on `ApplicationDriverVersion`
  (`content_hash`, `source_commit_sha`); composite `UNIQUE` index over
  the identity tuple; `cascade="all, delete-orphan"` on `actions` and
  `component_configs`; new `compute_driver_content_hash` helper;
  `GitDriverProvider.get_resolved_commit_sha`; repository
  `get_by_identity`; identity-aware load services for local and git
  paths.
- **GraphQL / SDK / CLI**: `ApplicationDriverVersion` exposes the new
  fields; SDK operations regenerated; CLI prints `<version>@<short>`
  labels and full fingerprint detail lines.
- **Frontend**: `formatDriverVersionLabel` helper threaded through the
  drivers list, driver detail page, deployment timeline, and config
  edit drawer; detail page shows the full hash/SHA with a copy button.
- **Docs / dev**: new `dev/guides/driver-iteration.md`; updates to
  `docs/docs/drivers/loading-drivers.md`,
  `docs/docs/concepts-and-architecture/what-is-a-driver.md`, and
  `docs/docs/changelog.md`; CONTEXT.md "Provenance fingerprint" entry;
  shard-marker list in `AGENTS.md` reconciled with the authoritative
  `_VALID_SHARDS` set in `backend/tests/e2e/conftest.py`.

## Test evidence

### E2E (Constitution §V)

`test_local_driver_reload_creates_new_row_on_content_change` —
`backend/tests/e2e/test_driver_reload_identity.py`. Full evidence in
[`specs/013-driver-fingerprint/e2e-pass-evidence.md`](e2e-pass-evidence.md):

- **Node ID**:
  `backend/tests/e2e/test_driver_reload_identity.py::test_local_driver_reload_creates_new_row_on_content_change`
- **Command**: `uv run pytest backend/tests/e2e/test_driver_reload_identity.py -v`
- **Run start (ISO 8601 UTC)**: `2026-05-25T16:09:13Z`
- **vCluster id**: `vcluster0` (under `pytest-224`)
- **Kubeconfig**: `/private/var/folders/jx/n90v5w6n15j834yyq8_j03nr0000gq/T/pytest-of-damien/pytest-224/vcluster0/kubeconfig`
- **PASSED line**:
  `backend/tests/e2e/test_driver_reload_identity.py::test_local_driver_reload_creates_new_row_on_content_change PASSED [100%]`
- **Summary**: `1 passed, 1 warning in 97.19s`

Shard marker is `shard_general` (the authoritative
`_VALID_SHARDS = {shard_general, shard_env, shard_compute, shard_backup,
shard_configuration}` does not include `shard_readonly`).

### Unit + propagation + integration

- Unit: hash helper, provider commit SHA, repository `get_by_identity`,
  cascade delete, labels (Python + TypeScript), loader behaviours for
  local and git paths.
- Propagation: `backend/tests/functional/graphql/test_application_driver_version_propagation.py`
  covers both new fields.
- CLI: `cli/tests/test_drivers.py` asserts the label and full
  fingerprint detail line.
- Frontend: `frontend/src/__tests__/driver-detail/VersionList.test.tsx`
  + the deployment-surface tests assert the `@<short>` label and the
  copyable full fingerprint on the detail page.

### Full suites

- `uv run invoke format lint` — clean.
- `uv run invoke test` — see CI / locally captured run.
- `cd frontend && pnpm test` — 52 files / 363 tests passing.

## Out of scope (follow-ups)

- `styrminctl drivers prune` — collapse unreferenced rows accumulated
  during iteration. Tracked separately.
- Recomputing fingerprints for legacy NULL rows on existing dev DBs —
  intentional dev-only consequence; production has no live data yet.

## Reviewer checklist

- [ ] Identity tuple matches `data-model.md` and the schema migration
      strategy (nullable columns + composite UNIQUE).
- [ ] Cascade-delete behaviour is exercised under test
      (`test_application_driver_version_get_by_identity.py`).
- [ ] Label helper is used consistently across CLI + frontend (no
      raw `version` string rendered on user-facing surfaces).
- [ ] Docs updated (`docs/docs/drivers/loading-drivers.md`, changelog,
      `dev/guides/driver-iteration.md`).
- [ ] CONTEXT.md "Provenance fingerprint" entry matches the shipped
      behaviour.
