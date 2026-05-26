# E2E PASS Evidence — spec 013 / US1 (Driver Reload Identity)

Captured per Constitution §V for chunk C8 (T026).

## T020 — `test_local_driver_reload_creates_new_row_on_content_change`

**Node ID**:

```
backend/tests/e2e/test_driver_reload_identity.py::test_local_driver_reload_creates_new_row_on_content_change
```

**Pytest command** (verbatim):

```
uv run pytest backend/tests/e2e/test_driver_reload_identity.py -v
```

**ISO 8601 timestamp** (run start, UTC): `2026-05-25T16:09:13Z`
**Run completed**: `2026-05-25T16:10:56Z` (elapsed ~97s)

**vCluster fixture id**: `vcluster0` (under `pytest-224`)

**Kubeconfig path**:

```
/private/var/folders/jx/n90v5w6n15j834yyq8_j03nr0000gq/T/pytest-of-damien/pytest-224/vcluster0/kubeconfig
```

**Verbatim PASSED line** (from pytest output):

```
backend/tests/e2e/test_driver_reload_identity.py::test_local_driver_reload_creates_new_row_on_content_change PASSED [100%]
```

**Summary**:

```
=================== 1 passed, 1 warning in 97.19s (0:01:37) ====================
```

## Notes

- Shard marker is `shard_general`, not the `shard_readonly` the task spec
  named. The conftest `_VALID_SHARDS` set
  (`backend/tests/e2e/conftest.py` lines 61-69) only accepts
  `shard_general / shard_env / shard_compute / shard_backup /
  shard_configuration`; `shard_readonly` is not in that set and would
  fail collection. `shard_general` is the closest fit for a read-heavy
  driver-load flow.
- The fixture chain `vcluster → styrmin_deployment →
  authenticated_styrmin_client` provisions a disposable vCluster on
  Docker, installs Styrmin via Helm, port-forwards the server, and logs
  in as the seeded admin — the test then `kubectl cp`s the committed
  local-driver fixture into the styrmin-server pod under a
  `uuid`-suffixed path so the load is hermetic.

## Unit-test corroboration (T021 + T022)

Run alongside the E2E to gate the service-layer wiring:

```
uv run pytest backend/tests/unit/services/test_applications_upsert_idempotent.py -v
```

```
backend/tests/unit/services/test_applications_upsert_idempotent.py::test_local_load_same_content_is_noop PASSED [ 50%]
backend/tests/unit/services/test_applications_upsert_idempotent.py::test_local_load_new_content_creates_new_row_without_deleting_old PASSED [100%]
============================== 2 passed in 0.16s ===============================
```
