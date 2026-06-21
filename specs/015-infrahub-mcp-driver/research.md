# Phase 0 Research: Infrahub MCP Server Application Driver

All "unknowns" here are confirmations against existing code/drivers rather than open technology choices — this is a config-only Driver reusing established machinery.

## R1 — Reference Driver to copy from

- **Decision**: Model the manifest on `driver/examples/infrahub/driver.styrmin.yml` (OCI Helm location, `info` block with links, internal `http` Service) and on `driver/examples/simple-app/driver.styrmin.yml` (single-Component shape). Use a **stripped-down** shape: one Component, one Service, parameters, **no `actions`**, **no `container_overrides`**, **no `backup`**.
- **Rationale**: `infrahub` shows the exact OCI `helm.main.location` pattern and an internal HTTP Service bound to a `server` Component; `simple-app` shows the minimal single-`server`-Component layout. The MCP Driver is simpler than both (no DB, no subcharts, no actions).
- **Alternatives considered**: Copy `infrahub` wholesale — rejected: it carries six Components, backups, container overrides, and three actions that the MCP server does not have.

## R2 — How "required parameter" is expressed

- **Decision**: Declare `infrahub_address` as `kind: string` with **no `default`**. Declare `mcp_read_only` (`kind: boolean`, `default: false`) and `mcp_log_level` (`kind: enum`, `values: [debug, info, warning, error]`, `default: info`).
- **Rationale**: `backend/styrmin_backend/services/driver/models/resources/parameters.py` has no `required` field. `validate_parameter_values` (`services/parameters/validator.py`) treats any parameter **without a default** as required and raises `ServiceError("Missing required parameter: '<name>'")` when omitted. So "required, no default" is the idiomatic encoding.
- **Alternatives considered**: Adding a `required: true` field — rejected: the model uses `extra="forbid"`, so an unknown key fails validation; "required = no default" is the supported convention.

## R3 — Enum parameter schema

- **Decision**: `mcp_log_level` uses `kind: enum` with `values: ["debug", "info", "warning", "error"]` and `default: "info"`.
- **Rationale**: `DriverParameterDefinition` supports `kind: enum` and requires a non-empty `values` list; the default must be a member of `values` (enforced by `validate_parameter`). The deploy-time validator (`_validate_value_type`) rejects values outside `values` with a `ServiceError`. This satisfies FR-003 and User Story 3.
- **Alternatives considered**: A free-form string for log level — rejected: FR-003 mandates enum validation so bad values fail before any render.

## R4 — Fixed `mcp.authMode: token-passthrough`

- **Decision**: Hardcode `mcp.authMode: token-passthrough` as a literal in `values.j2.yml`; do **not** expose it as a parameter. Declare **no** token parameter.
- **Rationale**: FR-004/FR-006 require passthrough to be fixed and no credential stored. Hardcoding in the template (like `simple-app`'s fixed `database.host`) keeps it out of the operator surface. There is no `secret` parameter kind in the model anyway (`DriverParameterKind` = string/integer/boolean/enum), so passthrough sidesteps the absent secret kind.
- **Alternatives considered**: A `mcp_auth_mode` enum parameter — rejected: out of scope; non-passthrough modes are explicitly excluded.

## R5 — Helm chart coordinates & pod selector label

- **Decision**: Use `helm.main.location: oci://registry.opsmill.io/opsmill/chart/infrahub-mcp`, `version: 0.1.0`; Component selector `app.kubernetes.io/name: infrahub-mcp`. **Confirm both at implementation** by inspecting the published chart `templates/` (Open Question carried from the PRD).
- **Rationale**: Follows the `infrahub` Driver's OCI pattern (`oci://registry.opsmill.io/opsmill/chart/<name>`). `app.kubernetes.io/name: <name>` is the standard Helm label convention and matches `simple-app`'s selector style.
- **Alternatives considered**: HTTP chart URL — rejected: the OpsMill registry serves OCI, consistent with the `infrahub`/`infrahub-enterprise` Drivers.
- **Risk/Mitigation**: If the published chart uses different coordinates or a different selector label, the implementation task adjusts the manifest before the deserialize test is finalized. Neither blocks the design; both are verified during implementation.

## R6 — `app.version` in the template

- **Decision**: The chart's app version is pinned via `helm.main.version` (chart `0.1.0`, appVersion `v1.1.6`). `values.j2.yml` does not need to template an image tag (the chart's appVersion handles it); only `infrahub.address`, `mcp.readOnly`, `mcp.logLevel`, `mcp.authMode`, and `fullnameOverride` are templated.
- **Rationale**: The MCP chart ships its own image/appVersion; unlike `simple-app` (which sets `image.tag: {{ app.version }}`), this Driver pins the chart version and lets the chart's defaults supply the image. Keeps the template minimal and matched to FR-004's required keys.
- **Alternatives considered**: Templating `image.tag` from `app.version` — deferred: not required by any FR; can be added if implementation finds the chart needs it.

## R7 — Test approach (E2E substitute)

- **Decision**: Extend `backend/tests/unit/services/driver/test_deserializer.py` to load and deserialize the real `driver/examples/infrahub-mcp/driver.styrmin.yml`, asserting: 1 Component (`server`), 1 Service (`infrahub-mcp`, http/internal/8001/component=server), exactly 3 parameters with correct kinds/defaults, and `actions == []`. Add parameter-validator tests (accept valid, reject unknown/wrong-type/out-of-enum/missing-required). Add a Jinja2 render test that renders `values.j2.yml` against a sample context and asserts `fullnameOverride: styrmin-infrahub-mcp`, `mcp.authMode: token-passthrough`, `infrahub.address`, `mcp.readOnly`, `mcp.logLevel`, and **absence of any `apiToken` key**.
- **Rationale**: These assertions exercise the Driver's entire external contract (parse + validate + render) without infrastructure. They are the owner-approved substitute for the E2E.
- **Alternatives considered**: A full E2E spinning up the MCP chart against a live Infrahub — rejected by owner as disproportionate (see plan Complexity Tracking).

## R8 — Documentation surfaces (FR-007)

- **Decision**: Add `infrahub-mcp` to the Examples list in `driver/DRIVERS.md` (existing list at the `## Examples` section) and to the example-driver list in `docs/docs/drivers/loading-drivers.md` (the "Where to put your own drivers" / reference-repo list).
- **Rationale**: Both surfaces already enumerate example Drivers (`infrahub`, `simple-app`, `slurpit`, `semaphore`, `db-test`). FR-007 requires both to reference `examples/infrahub-mcp`.
- **Alternatives considered**: A dedicated new docs page — rejected: out of proportion; the catalogue lists are the established discovery surface.
