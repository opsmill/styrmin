# ADR-045: Component-Scope Container Overrides — No Layering & Empty-List Marker

> Filename retains "omit-marker" for link stability; the design landed as the
> **empty-list marker** (see §2). The original omit-marker (research D8) was
> corrected during implementation because it broke clearing under the
> operator's JSON merge-patch HelmRelease apply.


**Status**: Accepted
**Date**: 2026-05-29
**Source**: specs/014-component-container-overrides/ (spec, plan, research)
**Relationship**: A faithful port of the deployment env-vars precedent (008/010,
[ADR-013](adr-013-driver-env-var-consumption.md)) with two deliberate
divergences recorded here. Reuses [ADR-029](adr-029-config-additions-via-baseconfigsection-no-migration.md)
(additive config rides existing JSON columns) and [ADR-018](adr-018-typed-update-deployment-input.md)
(typed `UpdateDeploymentInput.components` list).

## Context

Operators sometimes need to change a single component's container `command`
(entrypoint) and/or `args` for one deployment — to run a debug mode, a worker
variant, or to raise log verbosity — **without forking the application
driver**. This mirrors the env-vars feature almost exactly: per-component
config rides `DeploymentConfig.components[<name>]` (no migration), the typed
`updateDeployment` input carries the new fields, write-side validation rejects
unknown components and malformed lists, the render boundary tolerates orphans
after a driver upgrade, and drivers consume the resolved value through Jinja
template filters.

But `command`/`args` are not env vars, and two places legitimately diverge from
ADR-013. This ADR records those two divergences plus the per-field error
decision so a future maintainer doesn't relitigate them by "making it
consistent with env vars."

## Decision

### 1. No layering — component-scope only

Env vars merge `environment → deployment → component` per-key (deepest-wins).
`command`/`args` have **no** environment- or deployment-wide scope. The
resolved value is simply the component block's value (or "unset"). A dedicated
`ContainerOverridesResolver` does a **direct per-component lookup** plus orphan
detection — it does **not** reuse the env-vars `_merge_env_vars` primitive, and
the resolved context carries **no provenance field** (there is exactly one
possible source, so provenance is meaningless).

**Why.** Component entrypoints are heterogeneous: a single broad-scope
`command`/`args` that fans out to every component is semantically meaningless
(a server's entrypoint is unrelated to a database's). A deployment-wide
`command` would be a foot-gun, not a convenience. Skipping the merge keeps
resolution trivial and removes provenance bookkeeping that has no meaning here.

**Alternatives rejected.** Reusing `EnvVarsResolver` and passing only the
component layer — the dict-keyed deepest-wins merge does not model scalar
`list[str]` slots, and bending it in would obscure both features; a small
parallel resolver is clearer and keeps env-vars behaviour byte-identical
(SC-004). Allowing a deployment-scope `command`/`args` "for convenience" —
rejected by FR-003 and the Out-of-Scope section.

### 2. Empty-list marker — the filter returns `[]` when unset, the template always emits

The container-override filters (`component_command` / `component_args`) return
the resolved non-empty list when the operator has set an override, or **`[]`**
when unset. The driver template emits the key **unconditionally**
(`command: {{ components | component_command("server") | tojson }}`), and the
**chart** guards consumption with `{{- with .Values.command }}` — an empty list
is falsy, so the chart skips the key and the image/chart default applies. This
mirrors the env-vars `component_env_vars` always-present-list convention.

**Why an always-present key (not an omitted one) — the merge-patch
constraint.** The Styrmin operator applies the rendered HelmRelease
`spec.values` via JSON merge-patch (RFC 7386 —
`upsert_custom_resource` → `application/merge-patch+json`). Under merge-patch, a
key that is **absent** from the new values is left **unchanged**. So if the
driver template *omitted* `command`/`args` when the operator cleared an
override, the previously-set override would persist in the live `spec.values`
and **clearing would never reach the pod** (FR-007 / US3 would silently fail).
Emitting `[]` overwrites the prior value under merge-patch, and the chart's
`with` guard makes `[]` entrypoint-safe — it skips the key entirely, so the
image `ENTRYPOINT`/`CMD` (or chart default) applies, exactly as "unset" should.
A driver that declares but does not wire the filters stores-but-never-applies
the override (US6 silent no-op — identical to ADR-013's no-enforcement policy).

> **Note — superseded design.** The original spec/research (D8) prescribed an
> *omit-marker* (filter returns `None`, template guards with
> `{%- if _x is not none %}` and omits the key). Implementation E2E proved this
> silently breaks **clearing** under the merge-patch apply above: the cleared
> override never left the running pod. The empty-list marker is the corrected
> design; it preserves the same operator-visible behaviour (unset → chart/image
> default) while making clearing propagate.

**Alternatives rejected.** Keeping the omit-marker and switching the operator's
HelmRelease apply to a full replace / server-side apply — rejected: a broad,
risky change to the reconcile path for every custom resource, to work around a
driver-template convention that the empty-list marker solves locally.
Platform-side post-render injection of `command`/`args` — rejected for the same
reasons ADR-013 killed post-render env-var injection (the platform doesn't know
container names; the chart does). Rendering `command: []` into a chart that
consumes `.Values.command` *unconditionally* (no `with` guard) would blank the
entrypoint — hence the canonical chart pattern MUST use the `{{- with }}`
guard, which this ADR mandates.

### 3. Per-field typed errors — not reused from env vars

New `ServiceError` subclasses: `InvalidContainerCommandError`
(`INVALID_CONTAINER_COMMAND`), `InvalidContainerArgsError`
(`INVALID_CONTAINER_ARGS`), and `UnknownComponentContainerOverrideError`
(`UNKNOWN_COMPONENT_CONTAINER_OVERRIDE`, payload `component_name` +
sorted `known_components`). The env-vars `UnknownComponentEnvVarError` /
`INVALID_ENV_VAR_*` codes are **not** reused.

**Why.** Keeping the env-vars codes untouched preserves env-vars behaviour
byte-identical (SC-004), and the offending field must be identifiable as
`command` vs `args` (US4 Sc.3). A block carrying only `command`/`args` (no
`env_vars`) on an unknown component is *not* caught by the env-vars check (it
only inspects `env_vars`); the new check closes that gap for the new fields.
Validation runs at the **write** boundary (both the `deploy` create path and
the `updateDeployment` path), ahead of Pydantic so the typed code survives to
GraphQL, and before any reconcile (US4 — zero containers restarted on
rejection). Empty-string list elements are accepted (mirrors Kubernetes);
an empty list `[]` is rejected (clearing is null/omit, never `[]` — FR-007).

### 4. Validation shape: non-empty list-of-string, `[]` rejected

`validate_container_override(field, value)` accepts `None` (unset/clear),
requires a non-empty list when present, requires every element to be a string,
and accepts empty-string elements. Note that for the **typed**
`updateDeployment` input, a non-string element is rejected earlier by GraphQL's
`[String!]` coercion; the per-field typed code is exercised on the untyped
`config` JSON (`deploy`) path and via the Pydantic field validators.

## Consequences

- **Resolution stays trivial.** A direct O(components) dict lookup at render
  time; no merge, no provenance, negligible cost.
- **Drivers gain a precise, safe opt-in.** The chart's `{{- with }}` guard
  (which skips the empty-list marker) is the one thing a driver author must
  remember; the simple-app reference and the
  [driver consumption guide](../guides/driver-container-override-consumption.md)
  document the canonical shape.
- **Env-vars behaviour is unchanged.** The parallel `services/container_overrides/`
  module and the distinct error codes keep the env-vars feature byte-identical
  (SC-004); the no-regression run asserts it.
- **Driver upgrades stay non-destructive.** A stored override for a component
  the new driver no longer declares is preserved, flagged `isOrphaned: true` on
  read, and skipped by the renderer — reject-on-write, tolerate-on-read, the
  same load-bearing asymmetry as ADR-013.
- **Future work this opens up**: per-container targeting (v1 resolves exactly
  one `command`/`args` per component; the driver chooses the container);
  environment/deployment-scope overrides if a concrete use case ever emerges
  (deliberately closed off in v1).

## Alternatives Considered

- **Fold `command`/`args` into the env-vars resolver/filters/error types for
  "consistency".** Rejected — the shapes (`[String!]` lists vs `[EnvVar!]`),
  the layering semantics, and the empty-value meaning all differ; conflating
  them would obscure both features and risk env-vars regressions.
- **Single combined `containerOverride` object set/cleared atomically.**
  Rejected — forces read-modify-write to change one field and breaks the
  "clear `args`, keep `command`" story (US3 Sc.2). `command` and `args` are
  independent slots.
- **Treat `[]` as "clear".** Rejected by FR-007 — clearing is null/omit; `[]`
  is an explicit, rejected, invalid value, which keeps "clear" unambiguous and
  prevents an accidental empty-entrypoint container.
