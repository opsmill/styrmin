# Idea Brief: Component-scope `command` / `args` overrides

**Status**: Ready for /speckit-specify
**Source issue**: [opsmill/styrmin#283](https://github.com/opsmill/styrmin/issues/283)
**Seed**: Add support for overriding container `command` and `args` on application deployments at **component** scope only, following the env-vars pattern (#4 / #209). Operators need to change entrypoints / argument lists (debugging, runtime tuning, feature-flag CLI args, swapping a CLI into worker mode) without forking the driver. Surface: Pydantic `ComponentConfigBlock` fields, validation service, typed Jinja filters (`component_command` / `component_args`), GraphQL inputs on `deploy` / `updateDeployment`, frontend deployment / component editor, and a doc-only `command`/`args` declaration block in `driver.styrmin.yml`.

## Users and Value

**Primary user**: deployment operator (the persona who today edits a `Deployment` via SDK, CLI, or frontend to change parameters / env vars).

**Pain today**: the only way to change a container's `command` or `args` is to fork the **application driver** version (edit the Helm chart, re-publish). Legitimate operator-side reasons (debug entrypoint, feature-flag CLI arg, `--max-connections=…`, worker-mode swap) currently demand a driver fork.

**Smallest observable better**: an operator can set `command` / `args` on a single **component** via `updateDeployment`, the platform redeploys, and `kubectl get pod -o jsonpath='{.spec.containers[*].args}'` reflects the override — no driver fork, no chart edit.

## User Journeys

### P1 — Override `args` on a single component during deploy / update
- Journey: Operator picks an existing deployment, opens the component editor (or calls `updateDeployment`), sets `args=["--log-level=debug"]` on the `server` **component**, the **deployment** redeploys, the resulting pod's container runs with the new args.
- Given / When / Then:
  - **Given** a deployment exists with `driver=simple-app@v1`, `component=server`, no override set.
  - **When** the operator submits `updateDeployment` with `componentArgs: [{component: "server", args: ["--log-level=debug"]}]` (or its UI equivalent) and confirms the redeploy.
  - **Then** the new **instance** is generated, **reconciliation** plans an `UPDATE_INSTANCE` **flow**, the **StyrminDeployment** CRD is updated with the override embedded in the **GlobalContext**, FluxCD applies the new `HelmRelease`, and the `server` pod restarts with `.spec.containers[*].args == ["--log-level=debug"]`.

### P2 — Override `command` on the same component (independent of args)
- Journey: Same operator now needs to swap entrypoint for a one-off run (`python -m foo.cli worker` instead of the default `serve`). Setting `command` alone leaves `args` falling through to the chart default.
- Given / When / Then:
  - **Given** the same deployment with `componentArgs` already set on `server`.
  - **When** the operator sets `componentCommand: [{component: "server", command: ["python", "-m", "foo.cli", "worker"]}]` and leaves `args` untouched.
  - **Then** the rendered pod runs with the new `command` and the previously set `args`.

### P3 — Clear an override and fall back to the chart default
- Journey: Operator decides the override was a mistake and removes it. The pod redeploys with the driver's default `command` / `args`.
- Given / When / Then:
  - **Given** the deployment has `componentArgs` set on `server`.
  - **When** the operator submits `componentArgs: [{component: "server", args: null}]` (or omits the entry) and confirms redeploy.
  - **Then** the next **instance** has no `args` override; the Jinja filter returns the omit-marker; the chart's default args reach the pod.

## Functional Requirements (draft)

- **FR-001**: System MUST persist `command` and `args` on `ComponentConfigBlock` (the per-component override slot) as independent optional fields. Verifiable by a GraphQL **propagation test** writing each field and asserting the column on the merged `Deployment.config` JSON.
- **FR-002**: Users MUST be able to set `command` and/or `args` on any component declared by the **application driver version**, scoped to the **deployment** (no environment-scope override). Verifiable by an SDK call setting each independently, then reading them back.
- **FR-003**: On **write** (mutation boundary), system MUST reject overrides referencing a component name not declared by the driver, with a typed error (analogue to `UnknownComponentEnvVarError`). On **resolve** (render boundary), the resolver MUST tolerate orphan entries left over from a driver-version upgrade, emit them as `is_orphaned=True`, and skip them when rendering — mirroring env-vars US5 (FR-029..FR-033). Verifiable by (a) an SDK call submitting `component="ghost"` against a known driver and asserting the typed error, and (b) a unit test that simulates a driver upgrade dropping a component and asserts the orphan flag in the resolved context plus no override reaching the rendered chart values.
- **FR-004**: System MUST validate each override before any **reconciliation** runs: each list entry is a string, empty strings inside the list ARE accepted (mirrors Kubernetes container API and env-vars FR-007), the list is non-empty when set (no `[]` sentinel — explicit clear is `null`/omit). Verifiable by SDK calls submitting (a) `["sh", "-c", ""]` and asserting success, (b) `[]` and asserting `InvalidContainerCommandError` / `InvalidContainerArgsError`, (c) `[123]` (non-string entry) and asserting the typed error.
- **FR-005**: Drivers MUST be able to consume the resolved override via typed Jinja filters `component_command(<component_name>)` and `component_args(<component_name>)` returning a list of strings or `None`/omitted when no override is set. Verifiable by a unit test rendering a template that calls each filter against a context with / without the override.
- **FR-006**: Changing `command` or `args` MUST trigger the same redeploy-confirmation flow as env-var changes. Verifiable by reusing the existing redeploy-confirmation E2E hook for env-vars and asserting it fires for command/args.
- **FR-007**: `driver.styrmin.yml` MUST accept a doc-only `command` / `args` declaration block per component (analogous to `env_vars:`); the platform does not enforce that listed components actually wire the filter (informational, mirroring env-vars). Verifiable by parsing a driver spec with the new block and asserting it appears on the materialised `ApplicationDriverVersion`.
- **FR-008**: GraphQL `deploy` and `updateDeployment` mutations MUST accept a single nested input list `componentContainerOverrides: [{component: <name>, command: [<str>]?, args: [<str>]?}]` (mirrors `componentEnvVars` shape) and the matching read fields MUST return them, including orphan entries with an `is_orphaned` flag. Both `command` and `args` are optional and nullable per entry so partial updates and explicit clears work. Verifiable by **propagation tests** covering each field independently and the orphan-read path.

## Key Entities

- **ComponentConfigBlock** (existing, `backend/styrmin_backend/context/models/config.py:476`) — gains `command: list[str] | None` and `args: list[str] | None`. Already nullable JSON in `Deployment.config`.
- **Application driver** / **Application driver version** (existing) — driver spec parser gains optional `command` / `args` declaration block per component (doc-only, like `env_vars`).
- **GlobalContext** → `ComponentsContext` (existing) — already carries `env_vars` per component; absorbs `command` / `args` the same way.
- **Jinja filters** `component_command` / `component_args` — new, registered alongside `component_env_vars` in `agent/service/kubernetes/resources/builders/application.py`.

No new database tables, no new GraphQL root types.

## Edge Cases

- Operator sets a **new** override targeting a component name that does not exist in the selected driver version → typed error at the GraphQL boundary, no reconciliation (write-side strictness).
- Operator upgrades the driver version and a previously overridden component is **renamed or removed** in the new driver version → match env-vars (US5 / FR-029..FR-033): the stored block is preserved, the resolver emits an **orphan entry** (`is_orphaned=True`) carrying only the stored values, the renderer **skips orphans** so no override reaches the pod, and the GraphQL surface returns the orphan so the operator can see it and clean it up via standard mutations. Read-vs-write asymmetry by design.
- Driver author hasn't wired `component_command` / `component_args` into `values.j2.yml` → override stored, never reaches the pod (silent — same behaviour as env-vars per ADR-013).
- Override set, then the driver version is rolled back to one that pre-dates the filter → same silent-no-op as above.
- Multi-container component: the chart renders a pod with N containers. Resolved: the platform exposes one override per component and the driver author wires the filter call into whichever container they want. Targeting a non-default container in a multi-container pod is **not in scope** for v1.
- Concurrent `updateDeployment` calls both setting `args` on the same component → standard last-writer-wins on the JSON config column.
- Setting `command=[]` (empty list) → rejected at validation (`InvalidContainerCommandError`); explicit clear is `null` / omit.
- Setting `command=["sh", "-c", ""]` (empty string inside list) → accepted (mirrors K8s container API and env-vars FR-007).

## Success Criteria (draft)

- **SC-001**: An operator can set `args` on one component and observe it on the pod within one redeploy cycle, with **zero** driver-source changes required (no fork, no edit to `driver.styrmin.yml`, no chart edit) for drivers that have already wired the filter.
- **SC-002**: A driver author wires the override end-to-end (declaration in `driver.styrmin.yml`, filter call in `values.j2.yml`, optional chart-default fallback in `templates/deployment.yaml`) in ≤ 10 lines of changes across those three files.
- **SC-003**: Setting an invalid override (unknown component, empty list, malformed entry) MUST surface a typed error at the GraphQL boundary before any **flow** is submitted — zero pods restarted on rejection.
- **SC-004**: No regression: existing env-vars, parameters, and config E2Es pass unchanged.

## Constitution Alignment

- **§I Declarative**: ✅ Override is a field on the **deployment**'s config, diffed into the new **instance**, reconciled idempotently. No imperative side effects.
- **§II Driver-based deployment**: ✅ The driver opts in (declaration block + filter call). The platform never injects command/args without driver participation — mirrors env-vars post-010 behaviour.
- **§III Layered architecture**: ✅ GraphQL → service (validator) → repository (JSON column on `Deployment.config`). New filter registration is in the agent's renderer module — `agent/service/kubernetes/resources/builders/application.py`. No cross-layer shortcuts.
- **§IV Typed errors**: Three new `ServiceError` subclasses mirroring the env-vars precedent (`UnknownComponentEnvVarError` + `InvalidEnvVarName/Value`):
  - `UnknownComponentContainerOverrideError` — write-time, raised when a `componentContainerOverrides` entry targets a component name not declared by the driver. One class covers both fields (the unknown-component check is field-agnostic).
  - `InvalidContainerCommandError` — shape violation on `command` (non-string entry, empty list, wrong type).
  - `InvalidContainerArgsError` — same for `args`.
  Validation logic is shared in a helper (`validate_container_override_list(field, value)`); the two `Invalid*` classes diverge only in their `error_code` so clients can route on the field that failed.
- **§V E2E coverage**: New scenario — deploy a `simple-app`, set `componentArgs: [{component: "server", args: ["--log-level=debug"]}]` via SDK, assert `kubectl get pod -o jsonpath='{.spec.containers[*].args}'` matches. Dual-entrypoint (both `[api-chromium]` and `[ui-chromium]`).
- **§V GraphQL propagation**: ✅ Yes — new fields on `deploy` / `updateDeployment` inputs and on the read side. Propagation tests required for each.
- **§VII Documentation**: docs/ user-facing page (mirrors deployment-env-vars), `dev/guides/driver-env-var-consumption.md` sibling for command/args, ADR mirroring `adr-013`, `dev/knowledge/backend/` operator reference. `CONTEXT.md` likely unchanged (no new domain concept name).

## Governance Gates Crossed

- [x] **GraphQL schema change** — new input fields on `deploy` / `updateDeployment`, new read fields, new typed error codes.
- [ ] Database schema change — none expected (lands in existing `Deployment.config` JSON via Pydantic `ComponentConfigBlock` extension, per ADR-029).
- [ ] New dependency — none.
- [ ] CI/CD change — none.
- [ ] Auth change — none.

## Assumptions

- The Pydantic `ComponentConfigBlock` extension lands in the existing `Deployment.config` JSON column with no SQL migration (consistent with ADR-029 — config additions via `BaseConfigSection` need no migration). Verified against the model on disk; new fields add to the same `JSON` column.
- The doc-only driver declaration is informational only — platform does not enforce that a declared component actually wires the filter (matches env-vars policy in ADR-013 / `dev/guides/driver-env-var-consumption.md`).
- **One override per component, driver-wired.** The platform exposes exactly one resolved `command` and one resolved `args` per component to the rendering layer; the driver author chooses which container in the rendered chart the filter calls land on. Mirrors the env-vars contract (ADR-013): the platform never injects into a pod the driver template did not wire. The doc-only `command` / `args` declaration block in `driver.styrmin.yml` is where the driver author documents which container the override targets, so operators can read the spec before setting an override.
- For multi-container components today, v1 does **not** support targeting non-default containers — operators continue to fork the driver if they need that. A future iteration can add per-container granularity without breaking this contract.

## Out of Scope (v1)

- Environment-scope or deployment-scope command/args overrides (intentionally excluded — different components have heterogeneous entrypoints, so a single broader-scope override has no sensible semantics).
- Overriding other container fields (`image`, `resources`, `securityContext`, `workingDir`, env-vars-from-secret).
- Per-container override inside a multi-container pod with a stable contract — v1 surfaces one override per component, driver-wired; targeting non-default containers requires a future iteration.
- Templating / variable expansion inside override values (pass-through verbatim, same as env-vars).

## Open Questions

_None remaining. All grilling-stage clarifications resolved during this session._

## Notes / corrections

- The issue text references `adr-019-deployment-env-vars.md` and `adr-021-driver-env-var-consumption.md`, but those filenames do not exist in `dev/adr/`. The actual env-var driver-consumption ADR is **[`adr-013-driver-env-var-consumption.md`](../dev/adr/adr-013-driver-env-var-consumption.md)**. ADRs 019 and 021 cover unrelated topics (CRD phase coexistence, deployment CRD status snapshot). The deployment-env-vars side does not have a standalone ADR — the spec is at `specs/008-deployment-env-vars/` / `specs/010-driver-env-var-consumption/`.
