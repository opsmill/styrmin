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

- **Decision**: Use `helm.main.location: oci://registry.opsmill.io/opsmill/chart/infrahub-mcp`, `version: 0.1.0`; Component selector `app.kubernetes.io/name: infrahub-mcp`.
- **Status (T002): ✅ CONFIRMED against the published chart on 2026-06-21.** Verified by pulling the OCI artifact directly from `registry.opsmill.io` (Harbor on OVH) via the OCI distribution API with an anonymous pull token, then extracting and inspecting the chart tarball (`Chart.yaml`, `values.yaml`, `templates/`). `helm`/`oras`/`skopeo` were not on PATH in this environment, so the registry was queried with `curl` against `/v2/.../manifests/0.1.0` and the chart-content blob.
  - **OCI location**: `oci://registry.opsmill.io/opsmill/chart/infrahub-mcp` — CONFIRMED. `tags/list` returns `["0.1.0"]`.
  - **Chart version**: `0.1.0` — CONFIRMED (manifest annotation `org.opencontainers.image.version: 0.1.0`; Helm config blob `version: 0.1.0`).
  - **Pod selector label**: `app.kubernetes.io/name: infrahub-mcp` — CONFIRMED. `templates/_helpers.tpl` defines `infrahub-mcp.selectorLabels` as `app.kubernetes.io/name: {{ include "infrahub-mcp.name" . }}` + `app.kubernetes.io/instance: {{ .Release.Name }}`, and both `deployment.yaml` (`spec.selector.matchLabels` + pod template labels) and `service.yaml` (`spec.selector`) use that helper. `infrahub-mcp.name` resolves to `default .Chart.Name .Values.nameOverride`; the Driver sets `fullnameOverride` (not `nameOverride`), so `app.kubernetes.io/name` resolves to the chart name **`infrahub-mcp`**. The Styrmin Component selector key+value `app.kubernetes.io/name: infrahub-mcp` therefore matches the rendered pods.
- **Rationale**: Follows the `infrahub` Driver's OCI pattern (`oci://registry.opsmill.io/opsmill/chart/<name>`). `app.kubernetes.io/name: <name>` is the standard Helm label convention and matches `simple-app`'s selector style.
- **Alternatives considered**: HTTP chart URL — rejected: the OpsMill registry serves OCI, consistent with the `infrahub`/`infrahub-enterprise` Drivers.
- **Risk/Mitigation**: Resolved — coordinates and selector label are confirmed against the live chart; no remaining open question.

## R6 — `app.version` in the template

- **Decision**: The chart's app version is pinned via `helm.main.version` (chart `0.1.0`, appVersion `v1.1.6`). `values.j2.yml` does not need to template an image tag (the chart's appVersion handles it); only `infrahub.address`, `mcp.readOnly`, `mcp.logLevel`, `mcp.authMode`, and `fullnameOverride` are templated.
- **Status (T002): ✅ CONFIRMED against the published chart on 2026-06-21.**
  - **appVersion**: `v1.1.6` — CONFIRMED (Helm config blob `appVersion: v1.1.6`).
  - **Image default**: `image.repository: registry.opsmill.io/opsmill/infrahub-mcp`, `image.tag: ""` defaulting to `.Chart.AppVersion` via the `infrahub-mcp.image` helper — CONFIRMED. The chart supplies the image tag from appVersion, so the Driver does NOT template `image.tag`.
  - **Values key paths** (CONFIRMED verbatim from `values.yaml`):
    - `infrahub.address` (string; default `""`) — Infrahub server address.
    - `mcp.authMode` (string; chart default `"none"`; the Driver hardcodes `token-passthrough`). Chart-documented options: `none`, `token-passthrough`, `basic-passthrough`, `oidc`.
    - `mcp.readOnly` (boolean; chart default `false`).
    - `mcp.logLevel` (string; chart default `"info"`; documented options `debug`/`info`/`warning`/`error` — matches the Driver enum).
  - **Service port**: chart `service.port: 8001` / `service.targetPort: 8001` — CONFIRMED, matching the Driver's planned `infrahub-mcp` Service on port 8001.
  - **`fullnameOverride`**: supported top-level key (`values.yaml` `fullnameOverride: ""`) — CONFIRMED; setting it to `styrmin-infrahub-mcp` renames the Deployment/Service but does NOT change the `app.kubernetes.io/name` selector value (which derives from `nameOverride`/chart name; see R5).
  - **`infrahub.apiToken`**: the chart DOES expose an `infrahub.apiToken` block (`value`/`existingSecret`/`existingSecretKey`), but the Driver MUST NOT set it — token-passthrough mode means no stored credential. The render test (T006) asserts no `apiToken` key appears in the rendered values, which is the relevant guard.
- **Rationale**: The MCP chart ships its own image/appVersion; unlike `simple-app` (which sets `image.tag: {{ app.version }}`), this Driver pins the chart version and lets the chart's defaults supply the image. Keeps the template minimal and matched to FR-004's required keys.
- **Alternatives considered**: Templating `image.tag` from `app.version` — rejected: confirmed unnecessary, the chart defaults `image.tag` to appVersion `v1.1.6`.

## R7 — Test approach (E2E substitute)

- **Decision**: Extend `backend/tests/unit/services/driver/test_deserializer.py` to load and deserialize the real `driver/examples/infrahub-mcp/driver.styrmin.yml`, asserting: 1 Component (`server`), 1 Service (`infrahub-mcp`, http/internal/8001/component=server), exactly 3 parameters with correct kinds/defaults, and `actions == []`. Add parameter-validator tests (accept valid, reject unknown/wrong-type/out-of-enum/missing-required). Add a Jinja2 render test that renders `values.j2.yml` against a sample context and asserts `fullnameOverride: styrmin-infrahub-mcp`, `mcp.authMode: token-passthrough`, `infrahub.address`, `mcp.readOnly`, `mcp.logLevel`, and **absence of any `apiToken` key**.
- **Rationale**: These assertions exercise the Driver's entire external contract (parse + validate + render) without infrastructure. They are the owner-approved substitute for the E2E.
- **Alternatives considered**: A full E2E spinning up the MCP chart against a live Infrahub — rejected by owner as disproportionate (see plan Complexity Tracking).

## R8 — Documentation surfaces (FR-007)

- **Decision**: Add `infrahub-mcp` to the Examples list in `driver/DRIVERS.md` (existing list at the `## Examples` section) and to the example-driver list in `docs/docs/drivers/loading-drivers.md` (the "Where to put your own drivers" / reference-repo list).
- **Rationale**: Both surfaces already enumerate example Drivers (`infrahub`, `simple-app`, `slurpit`, `semaphore`, `db-test`). FR-007 requires both to reference `examples/infrahub-mcp`.
- **Alternatives considered**: A dedicated new docs page — rejected: out of proportion; the catalogue lists are the established discovery surface.
