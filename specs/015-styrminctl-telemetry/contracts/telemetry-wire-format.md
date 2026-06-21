# Contract: Telemetry wire format (HTTPS POST body)

**Feature**: `015-styrminctl-telemetry`

The CLI POSTs exactly this envelope to the telemetry endpoint. This is the authoritative client-side
contract; the ingestion endpoint is out of scope.

## Transport

- Method: `POST`
- URL: `STYRMIN_TELEMETRY_ENDPOINT` if set, else the default production endpoint.
- Content-Type: `application/json`
- Body: the envelope below (UTF-8 JSON).
- The server adds the ingestion `timestamp` and any geo/IP enrichment. The client sends **no**
  timestamp and **no** network identifier.

## Envelope

```json
{
  "data": {
    "event_id": "a1b2c3d4-deployments_update",
    "install_id": "a1b2c3d4e5f6...",
    "command": "deployments update",
    "options": ["--config", "--wait"],
    "outcome": "success",
    "error_category": null,
    "styrminctl_version": "0.1.0",
    "python_version": "3.14.0",
    "os_family": "Linux"
  },
  "checksum": "<sha256 hex of json.dumps(data)>",
  "kind": "styrminctl",
  "payload_format": "1.0"
}
```

### Envelope invariants

- `kind` is the constant string `"styrminctl"`.
- `payload_format` is the constant string `"1.0"`.
- `checksum` equals `hashlib.sha256(json.dumps(data).encode("utf-8")).hexdigest()` where
  `json.dumps(data)` uses CPython defaults (separators `", "`/`": "`, **insertion** key order, no
  `sort_keys`, `ensure_ascii=True`). A server reproducing `pythonJsonStringify(data)` + SHA-256
  recomputes the identical digest (SC-005).

### `data` invariants

- Keys are **exactly** (and only) `event_id, install_id, command, options, outcome, error_category,
  styrminctl_version, python_version, os_family`, in that insertion order.
- `command` ∈ the closed set of resolved command routes.
- Every element of `options` is a canonical long-form name (`--xxx`) ∈ that command's declared option
  set; the array is deduplicated and sorted; positionals and repeat-counts are excluded; **no value**
  ever appears.
- `outcome` ∈ {`"success"`,`"failure"`}. `error_category` is `null` iff `outcome == "success"`,
  else ∈ {`auth`,`network`,`validation`,`not_found`,`server`,`usage`,`unknown`}.
- `os_family` ∈ {`Linux`,`Darwin`,`Windows`}.
- **Forbidden** anywhere in the body (FR-008): server address, hostnames, usernames, tokens,
  deployment/cluster/environment names, argument/option values, file paths, IPs.

## Dispatch behaviour (observable)

- At most **one** POST per eligible invocation, sent after the outcome is known.
- Best-effort: no retry, no batching, no on-disk spool.
- Hard latency cap: adds ≤ 200 ms (p99, single tunable constant) to command exit for **all** endpoint
  states including a hung connection.
- Failure-isolated: any endpoint error (refused/hung/DNS/4xx/5xx) or internal telemetry error is
  swallowed; exit code, stdout, and stderr are byte-identical to the telemetry-disabled run.

## Fixed checksum round-trip vector (test anchor — SC-005)

For a `data` object with these exact values and key order:

```
event_id=a1b2c3d4-deployments_update, install_id=a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6,
command=deployments update, options=["--config","--wait"], outcome=success,
error_category=null, styrminctl_version=0.1.0, python_version=3.14.0, os_family=Linux
```

`json.dumps(data)` and its SHA-256 hex digest are pinned in the unit test
`build_envelope` round-trip vector and MUST match a server-side `pythonJsonStringify` + sha256
recomputation. (The literal digest is computed and asserted in the test, not hand-copied here.)
