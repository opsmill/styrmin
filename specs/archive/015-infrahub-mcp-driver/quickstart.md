# Quickstart / Validation Guide: Infrahub MCP Server Driver

How to validate the `infrahub-mcp` Driver end-to-end at the unit level (the
owner-approved substitute for an E2E). All commands run from the repo root.

## Prerequisites

- `uv sync` has installed backend dependencies.
- Branch `015-infrahub-mcp-driver` checked out.
- Driver files present at `driver/examples/infrahub-mcp/driver.styrmin.yml` and `.../values.j2.yml`.

## 1. Manifest validates (deserialize)

The deserializer must parse the manifest with zero errors and expose the
expected Component/Service/parameters (see `contracts/driver-manifest.md`).

```bash
uv run pytest backend/tests/unit/services/driver/test_deserializer.py -v
```

Expected: the new `infrahub-mcp` deserialize test passes — 1 `server` Component,
1 `infrahub-mcp` http/internal/8001 Service, 3 parameters (`infrahub_address`
required string, `mcp_read_only` boolean default false, `mcp_log_level` enum
default info), `actions == []`. (SC-001.)

## 2. Parameters validate (accept/reject)

```bash
uv run pytest backend/tests/unit/services/parameters/ -v -k infrahub_mcp
```

Expected: deploying with only `infrahub_address` resolves defaults
(`mcp_read_only=false`, `mcp_log_level=info`) — SC-003; omitting
`infrahub_address`, supplying an unknown param, a non-boolean `mcp_read_only`,
or an out-of-enum `mcp_log_level` each raises `ServiceError`.

## 3. Values render correctly (template)

```bash
uv run pytest backend/tests/unit/services/driver/ -v -k "infrahub_mcp and render"
```

Expected (see `contracts/rendered-values.md`): rendered YAML contains
`fullnameOverride: styrmin-infrahub-mcp`, `mcp.authMode: token-passthrough`,
`mcp.readOnly`, `mcp.logLevel`, and `infrahub.address` mapped from parameters —
and contains **no** `apiToken` key anywhere (SC-002, SC-004).

## 4. Lint & format

```bash
uv run invoke format lint
```

Expected: clean (Constitution §VI).

## 5. Docs reference the new Driver (FR-007)

```bash
grep -n "examples/infrahub-mcp\|infrahub-mcp" driver/DRIVERS.md docs/docs/drivers/loading-drivers.md
```

Expected: both files reference `infrahub-mcp`.

## Done When

- Steps 1–3 pass (deserialize + parameter validation + render).
- Step 4 is clean.
- Step 5 shows both docs surfaces updated.
- No E2E is run (owner-approved; recorded in plan Complexity Tracking).

## Manual smoke (optional, not part of CI)

If a published `infrahub-mcp` chart and a reachable Infrahub are available,
load the Driver locally and create a Deployment supplying only
`infrahub_address`; confirm a running `server` Component and the internal
`infrahub-mcp` Service on 8001 (User Story 1). Out of scope for the automated
gate.
