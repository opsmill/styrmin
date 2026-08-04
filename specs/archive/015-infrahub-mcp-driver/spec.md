# Feature Specification: Infrahub MCP Server Application Driver

**Feature Branch**: `015-infrahub-mcp-driver`

**Created**: 2026-06-21

**Status**: Extracted

**Input**: User description: "PRD: Infrahub MCP server Application Driver" (https://github.com/opsmill/styrmin/issues/271#issuecomment-4762259894)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Deploy an Infrahub MCP server in passthrough mode (Priority: P1)

An operator who already runs an Infrahub instance wants to expose it to AI agents and IDE clients over the Model Context Protocol. They open Styrmin, choose the `infrahub-mcp` Driver, supply the address of their target Infrahub instance, and deploy. Styrmin stands up a managed, reconciled MCP service running in token-passthrough auth mode — the calling AI client forwards its own Infrahub token per request, so no credential is ever stored in or surfaced by Styrmin. The server is a lightweight standalone service that connects to the existing Infrahub; it does not deploy Infrahub itself.

**Why this priority**: This is the entire feature. Without it there is no first-class, declarative way to stand up the Infrahub MCP server next to the infrastructure it serves — operators are left with Docker Compose outside the platform, missing lifecycle management, reconciliation, and observability.

**Independent Test**: Load the `infrahub-mcp` Driver, create a Deployment supplying only `infrahub_address`, and verify Styrmin renders valid Helm values (`fullnameOverride: styrmin-infrahub-mcp`, `mcp.authMode: token-passthrough`, `infrahub.address` set) and produces a running `server` Component that exposes the internal `infrahub-mcp` HTTP Service on port 8001.

**Acceptance Scenarios**:

1. **Given** an operator with a reachable Infrahub instance and the `infrahub-mcp` Driver loaded, **When** they create a Deployment supplying `infrahub_address` (optionally `mcp_read_only` / `mcp_log_level`), **Then** Styrmin renders valid Helm values with `fullnameOverride: styrmin-infrahub-mcp`, `mcp.authMode: token-passthrough`, and `infrahub.address` set, and the Deployment produces a running `server` Component exposing the internal `infrahub-mcp` HTTP Service on port 8001.
2. **Given** the `infrahub-mcp` Driver, **When** an operator deploys supplying only `infrahub_address`, **Then** `mcp_read_only` defaults to `false` and `mcp_log_level` defaults to `info`, and the Deployment proceeds without requiring any other input.

---

### User Story 2 - Restrict the MCP server to read-only access (Priority: P2)

An operator wants to safely expose query-only access to less-trusted agents. They set the MCP server to read-only for that specific deployment so that agents can read infrastructure data but cannot mutate it.

**Why this priority**: Read-only mode is a meaningful safety control that broadens who the server can be exposed to, but the feature is still valuable without it (defaults to read/write off, i.e. `false`).

**Independent Test**: Create a Deployment with `mcp_read_only: true` and verify the rendered Helm values contain `mcp.readOnly: true`.

**Acceptance Scenarios**:

1. **Given** the `infrahub-mcp` Driver, **When** an operator sets `mcp_read_only: true`, **Then** the rendered Helm values contain `mcp.readOnly: true`.
2. **Given** the `infrahub-mcp` Driver, **When** an operator does not set `mcp_read_only`, **Then** the rendered Helm values contain `mcp.readOnly: false`.

---

### User Story 3 - Tune the MCP server log level per deployment (Priority: P3)

An operator wants to debug agent interactions without changing the Driver. They set the log level for a specific deployment to `debug`, `info`, `warning`, or `error`.

**Why this priority**: Operational convenience that aids debugging, but not essential to the core deploy flow.

**Independent Test**: Create a Deployment with `mcp_log_level: debug` and verify the rendered Helm values contain `mcp.logLevel: debug`; supply an out-of-enum value and verify it is rejected before any render.

**Acceptance Scenarios**:

1. **Given** the `infrahub-mcp` Driver, **When** an operator sets `mcp_log_level` to one of `debug`/`info`/`warning`/`error`, **Then** the rendered Helm values contain the matching `mcp.logLevel`.
2. **Given** the `infrahub-mcp` Driver, **When** an operator supplies an `mcp_log_level` outside the enum, **Then** the parameter validator rejects the value before any render occurs.

---

### User Story 4 - Discover and catalogue the new Driver (Priority: P3)

A platform engineer wants the new Driver to load and validate cleanly against the `DRIVERS.md` schema so a malformed manifest fails fast at load time. A docs reader wants the Driver catalogued alongside the other example Drivers so it can be discovered and copied.

**Why this priority**: Load-time validation and discoverability are necessary for a maintainable, usable Driver, but flow from the core deliverable.

**Independent Test**: Run the driver-load path against the new manifest and confirm zero validation errors with no `actions.py` requirement; confirm `driver/DRIVERS.md` and the relevant `docs/` drivers page both reference `examples/infrahub-mcp`.

**Acceptance Scenarios**:

1. **Given** the new manifest, **When** the driver-load path runs, **Then** it succeeds with zero validation errors and requires no `actions.py`.
2. **Given** the documentation, **When** a reader looks at `driver/DRIVERS.md` and the `docs/` drivers catalog, **Then** both reference `examples/infrahub-mcp`.

---

### Edge Cases

- **Unreachable / wrong `infrahub_address`**: The server still starts. Passthrough resolves Infrahub per request with the client's token, so connection failures surface at agent-query time, not at deploy time. Acceptable for v1.
- **`infrahub_address` omitted**: Rejected at deploy time by the parameter validator (required, no default).
- **Invalid `mcp_log_level`**: Rejected by enum validation before any render.
- **Future MCP v2**: Excluded by `supported_versions: >=1.1,<2.0`; adopting v2 requires a deliberate Driver bump.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The Driver MUST declare `metadata.name: infrahub-mcp`, `spec.version`, `supported_versions: ">=1.1,<2.0"`, an `info` block (description + upstream links), and `helm.main.location`/`version`. *(Verify: driver deserializes and schema validation passes.)*
- **FR-002**: The Driver MUST define exactly one `server` Component (`identifier.label: app.kubernetes.io/name: infrahub-mcp`) and exactly one `http` Service named `infrahub-mcp`, `scope: internal`, `port: 8001`, bound to `server`. *(Verify: parsed Driver model exposes the Component and the Service with those attributes.)*
- **FR-003**: Operators MUST be able to set `infrahub_address` (string, required, no default), `mcp_read_only` (boolean, default `false`), and `mcp_log_level` (enum `debug`/`info`/`warning`/`error`, default `info`). The parameter validator MUST accept valid values and reject unknown names, wrong types, and out-of-enum values. *(Verify: parameter validator accepts valid values and rejects unknown names / wrong types / out-of-enum values.)*
- **FR-004**: `values.j2.yml` MUST render from a Deployment context with `fullnameOverride: styrmin-infrahub-mcp`, `mcp.authMode: token-passthrough` (fixed, not operator-settable), and parameter values mapped to `infrahub.address`, `mcp.readOnly`, and `mcp.logLevel`. *(Verify: Jinja2 render against a sample context produces valid YAML containing those keys.)*
- **FR-005**: The Driver MUST load and validate cleanly per `DRIVERS.md` with no `actions` declared and no `actions.py` file. *(Verify: the driver-load path succeeds with zero validation errors and no `actions.py` requirement.)*
- **FR-006**: The Driver MUST NOT store or surface any Infrahub token. No token parameter exists, and rendered values MUST contain no `infrahub.apiToken` (or any `apiToken`) key. *(Verify: manifest declares no token parameter; rendered values omit any `apiToken` key.)*
- **FR-007**: The new Driver MUST be catalogued in `driver/DRIVERS.md` and the relevant `docs/` drivers page; both MUST reference `examples/infrahub-mcp`. *(Verify: both documents reference `examples/infrahub-mcp`.)*

### Key Entities

- **Driver** *(new instance of an existing concept)*: `infrahub-mcp` — a new versioned deployment specification. No new entity *type* is introduced.
- **Component** *(existing)*: a single `server` Component selected by `app.kubernetes.io/name: infrahub-mcp`.
- **Service** *(existing)*: `infrahub-mcp`, `kind: http`, `scope: internal`, `port: 8001`, owned by `server`; materialised as a `DeployedService` + Kubernetes Service.
- **Parameter** *(existing)*: three parameters — one string (`infrahub_address`), one boolean (`mcp_read_only`), one enum (`mcp_log_level`). No new parameter kind is required (token-passthrough avoids the absent `secret` kind).
- No Database table, GraphQL type, or new platform entity is introduced.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Loading the Driver succeeds and surfaces exactly three parameters, one Service, and one Component, with zero schema/validation errors.
- **SC-002**: For a sample Deployment context with `infrahub_address` set, `values.j2.yml` renders to valid YAML containing `fullnameOverride: styrmin-infrahub-mcp`, `mcp.authMode: token-passthrough`, and the mapped `infrahub.address`.
- **SC-003**: A new operator can produce a deploying MCP Service supplying only `infrahub_address`, with all other inputs defaulted (`mcp_read_only: false`, `mcp_log_level: info`).
- **SC-004**: Rendered Helm values for any valid parameter combination contain no `apiToken` key, confirming no credential is stored or surfaced by the platform.

## Assumptions

- The upstream `infrahub-mcp` Helm chart is published to `oci://registry.opsmill.io/opsmill/chart/infrahub-mcp` at version `0.1.0` (appVersion `v1.1.6`), following the `infrahub` Driver's OCI pattern. The exact OCI coordinates and chart `version` will be confirmed at implementation by inspecting the chart; this does not block the design.
- The chart's pod selector label is `app.kubernetes.io/name: infrahub-mcp` (standard Helm convention); confirmed at implementation against the chart `templates/`.
- `mcp.authMode: token-passthrough` requires no server-side token; the MCP client forwards its Infrahub token per request.
- The MCP server image is `registry.opsmill.io/opsmill/infrahub-mcp`.
- The transport (streamable-HTTP) and port (8001) are fixed by the Driver and not exposed as operator parameters.
- The existing Driver-params form, parameter validator, and Component + Service + reconciliation machinery are reused unchanged; no new Driver capability, Component type, GraphQL surface, service-layer error, SDK, CLI, or frontend code is introduced.
- The owner has approved (this session) the **New dependency** governance gate (upstream `infrahub-mcp` Helm chart + image) and the **Skipping E2E coverage** gate; both are honored, not re-litigated. Unit-level deserialize + render checks (extending `backend/tests/unit/services/driver/test_deserializer.py` and the parameter-validator suite) are the agreed substitute for an E2E scenario.

## Out of Scope

- E2E test coverage (explicit owner decision; deviation from Constitution §V recorded here and honored).
- Non-passthrough auth modes (`none`, `basic-passthrough`, `oidc`).
- Exposing the transport or port as parameters (fixed: streamable-HTTP, 8001).
- Deploying or bundling Infrahub itself (covered by the `infrahub` Driver / #270).
- Ingress / external scope, setup/upgrade actions, and backups.
- Any GraphQL, Database, SDK, CLI, or frontend change.
