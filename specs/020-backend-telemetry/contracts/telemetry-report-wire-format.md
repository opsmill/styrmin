# Contract: Server telemetry report (HTTPS POST body)

**Feature**: `020-backend-telemetry`

The server sends exactly this body to the telemetry endpoint once a day. It reuses the envelope of the `styrminctl` report ([wire format of spec 015](../../archive/015-styrminctl-telemetry/contracts/telemetry-wire-format.md)) with a different `kind` and its own `data` keys. The ingestion endpoint is out of scope.

## Transport

- Method: `POST`
- URL: `STYRMIN_TELEMETRY_ENDPOINT` when set and not blank, otherwise `https://telemetry-endpoints.cloudflare-096.workers.dev/styrmin` (research D4).
- Content-Type: `application/json`
- Body: the envelope below, UTF-8 JSON.
- No authentication header, no cookie, no timestamp and no network identifier. The ingestion endpoint adds the time it received the report.
- One attempt per daily run. No retry, no queue, no batching (spec FR-012, edge case "install is down").
- The attempt stops after 10 seconds in total, whatever the endpoint does (FR-009, research D8).
- Any status outside 2xx counts as a failed send. A failed send is logged at debug level and the flow run ends `Completed` (FR-008).

## Envelope

```json
{
  "data": {
    "install_id": "0b6f4f0e-6d0e-4a55-9a51-2f8c3f7c9f0d",
    "styrmin_version": "0.1.48",
    "python_version": "3.14.0",
    "os_family": "Linux",
    "arch": "x86_64",
    "cluster_count": 1,
    "environment_count": 3,
    "deployment_count": 5,
    "drivers": [
      {"name": "infrahub", "version": "1.2.0", "source_type": "git", "deployment_count": 2},
      {"name": "semaphore", "version": "0.4.1", "source_type": "local", "deployment_count": 0},
      {"name": "styrmin-ingress-controller", "version": "1.0.0", "source_type": "internal", "deployment_count": 3}
    ]
  },
  "checksum": "<sha256 hex of json.dumps(data)>",
  "kind": "styrmin",
  "payload_format": "1.0"
}
```

The driver names and counts above are examples, not real values.

### Envelope invariants

- `kind` is the constant string `"styrmin"`. `styrminctl` reports keep `"styrminctl"`.
- `payload_format` is the constant string `"1.0"` (research D5). It changes only when the `data` keys or their meaning change.
- `checksum` equals `hashlib.sha256(json.dumps(data).encode("utf-8")).hexdigest()` with CPython defaults: separators `", "` and `": "`, insertion key order, no `sort_keys`, `ensure_ascii=True`. This is the same rule as for `styrminctl`, so the ingestion endpoint verifies both kinds with one function (FR-007).

### `data` invariants

- The keys are exactly `install_id`, `styrmin_version`, `python_version`, `os_family`, `arch`, `cluster_count`, `environment_count`, `deployment_count`, `drivers`, in that insertion order (FR-006).
- `install_id` is the canonical lowercase string form of a UUID4, the same value in every report from one database (FR-014).
- `styrmin_version` is the Styrmin release version, read from the `project.version` of the workspace `pyproject.toml`, or `"unknown"` when that file cannot be read (research D6).
- `python_version` is `platform.python_version()`.
- `os_family` is `platform.system()`, for example `Linux`.
- `arch` is `platform.machine()`, for example `x86_64` or `aarch64`.
- `cluster_count` and `environment_count` count all rows. `cluster_count` is 0 or 1 ([ADR-039](../../../dev/adr/0039-single-cluster-platform-scope.md)).
- `deployment_count` counts deployments that are not tombstoned (`deleted_at IS NULL`), including internal deployments (spec edge cases).
- `drivers` has one entry per distinct `(name, version, source_type)` of the loaded application driver versions, including entries with `deployment_count: 0` (FR-001, research D9).
  - Each entry has exactly the keys `name`, `version`, `source_type`, `deployment_count`, in that order.
  - `name` is the application driver name as the operator wrote it.
  - `source_type` is the stored `applicationdriverversion.source_type`: `git` or `local` for driver versions loaded from a driver source (`services/applications.py`), or `internal` for the ingress controller driver `styrmin-ingress-controller` that Styrmin creates (`services/ingress_controller/driver.py`). The column is a free string, so a future source type would be reported as stored.
  - `deployment_count` is the number of deployments that are not tombstoned and are bound to one of the driver versions merged into the entry.
  - Entries are sorted by `name`, then `version`, then `source_type`, so the same database state always gives the same `data` and the same checksum.
- Forbidden anywhere in the body (FR-002, FR-006): driver source repository URL, branch or path, provenance fingerprint, cluster, environment or deployment names, hostnames, IP addresses, user names, tokens, configuration values, parameters.

## Fixed checksum vector (test anchor)

A unit test builds `data` with fixed values in the order above, computes the checksum with the server's function, and asserts it equals the checksum that `styrminctl.telemetry.envelope.checksum` computes for the same `data` (research D3). The digest itself is computed in the test, not copied here.
