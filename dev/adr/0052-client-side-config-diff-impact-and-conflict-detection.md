# ADR-052: Client-side configuration diff, impact heuristic, and conflict detection

**Status**: Accepted
**Date**: 2026-08-04
**Source**: specs/archive/011-unified-deployment-config/research.md (R-003, R-004, R-005, R-012, R-013)
**Related**: [ADR-015](0015-frontend-value-transform-boundary.md) (the submit-boundary
transform this feeds), [ADR-018](0018-typed-update-deployment-input.md) (the
full-replacement input being diffed), [ADR-012](0012-environment-config-fanout.md) (the
environment config whose values show as "inherited").

## Context

Deployment configuration was scattered across a scheduling-only modal, a
read-only JSON dump, and the create form. The unified Configuration tab and edit
drawer put all eight config sections in one place — which means one submit can
change anything from a deployment's name to its topology-spread constraints,
against a mutation with **full-replacement** semantics.

That raises three problems the UI has to solve before it fires
`updateDeployment`:

1. **What am I about to change?** A full-replacement payload carries every
   field, so the payload itself cannot tell the operator what moved.
2. **What will it do to my running pods?** Some config edits are cosmetic;
   others drain pods off tainted nodes. The platform has no dry-run endpoint.
3. **Did someone else change this while I was editing?** The drawer is a
   long-lived editing surface over a mutable row, and silent last-write-wins was
   explicitly rejected by the spec.

## Decision

All three are solved **client-side**, with no backend change, and each behind an
interface that a future backend implementation can drop into unchanged.

### 1. A hand-rolled structural diff keyed on stable identifiers

`frontend/src/lib/config-diff.ts` walks the typed `UpdateDeploymentInput` once
and emits `DiffEntry { section, path, label, before, after, kind }`. No generic
diff library.

The load-bearing property is that **array entries are keyed by their stable
identifier — env-var name, toleration key, component name — never by position**.
Reordering env vars is not a change. A generic library returns positional JSON
Patch operations and would report a reorder as two edits; re-classifying that
output into sections and human labels costs more than the ~80-line walk.

Every entry is attributed to a `SectionId` during the walk. That attribution is
what powers the diff dialog's per-section headers and the drawer nav rail's
change dots — a generic diff has no notion of a section.

### 2. Impact is a declarative rule table, evaluated to a stable summary shape

`lib/impact-rules.ts` is an array of `{matcher, consequence, severity}`.
`lib/config-impact.ts` evaluates it against a `ConfigurationDiff` and returns an
`ImpactSummary` with a deduplicated consequence list and a `topSeverity`;
`topSeverity === "high"` flips the dialog into its disruptive treatment.

Matchers use a minimal glob over the dotted path — `*` is one segment, `**` is
many — plus a `value:X` qualifier for value-sensitive rules
(`scheduling.tolerations[*].effect value:NO_EXECUTE`). No regex.

**The rules are explicitly approximate and expected to be wrong at the edges.**
They encode what we believe restarts pods; they will be refined as production
shows what actually does. That is acceptable because the dialog is advisory — it
never blocks or alters the mutation.

**The seam is the point.** When a backend `previewUpdateDeployment` query lands,
`config-impact.ts` swaps rule evaluation for a query call and the consumer sees
the same `ImpactSummary`. Keeping the table in TypeScript rather than JSON is
what lets matchers, severities, and their unit tests sit together.

### 3. Inheritance is computed on the client from the parent environment config

`lib/config-inheritance.ts` compares the deployment's config against
`deployment.environment.config` — already available on the existing
`get_deployment` query — and returns per-section
`{state: 'inherited' | 'overridden', overrideCount}`.

A section is *overridden* when it has at least one field whose value differs from
the environment's (or is set where the environment has none), *inherited*
otherwise. Two sections are special-cased: Driver Parameters has no environment
equivalent, so it compares against the driver's declared defaults; Component
Overrides is "inherited" exactly when no per-component block exists.

A backend-computed per-group flag would be a schema change for a 30-line
function operating on data the client already holds.

### 4. Concurrent edits: client-side fingerprint compare, forced reload

**Strategy B shipped.** On Apply, `ConfigDiffDialog`:

1. Re-fetches `GetDeployment` in the foreground.
2. Hashes `{name, parameters, config}` on the refreshed row and compares it to
   the same hash captured at drawer-open time.
3. **Unchanged** → dispatch `updateDeployment`, invalidate `GetDeployment`.
4. **Changed** → render an in-dialog `ConflictPanel`. The mutation does not
   proceed.

The Reload action hands the refreshed deployment back to `ConfigEditDrawer`,
which **swaps its baseline to the new persisted state while keeping the
operator's pending edits**. The operator's work is never discarded; only the
thing their edits are measured against moves.

Forced reload with no "overwrite anyway" escape hatch is the v1 default. An
override can be added if operators turn out to need it.

**Strategy A — a server-issued `updatedOn` stamp plus a typed
`STALE_DEPLOYMENT_WRITE` error — is deferred, not rejected.** The plan-phase
audit confirmed `Deployment.updated_on` already exists on the row (from
`StyrminModel`, with `onupdate=func.now()`) and is simply not exposed on the
Strawberry type; `crdStatus.updatedOn` is unsuitable because it tracks the agent's
status stream, not spec edits. Exposing it is purely additive. The reason to
wait: the v1 race window is a single round-trip, the UX is identical, and the
dialog's `setConflictDeployment` path will be driven by a typed error response
just as readily as by a fingerprint mismatch — so the backend change can land
later without touching dialog code.

### 5. Env-var values stay in plaintext — deliberately

The drawer renders env-var values in plaintext, matching what `View JSON`, the
SDK, and the Kubernetes ConfigMap already expose. **The feature introduces no new
exposure surface, but it does make these values one click more discoverable.**

Anyone with deployment-read access can already read `deployment.config`, which
embeds them. Masking behind a "Reveal" toggle was rejected because it implies the
UI is the trust boundary when the GraphQL response carries the plaintext
regardless — a false assurance is worse than none. `EnvVar.value` is documented
as not being for secret material; a real secrets facility (Secret references,
external managers) is a separate workstream, and blocking env-var editing until
it lands was not an acceptable trade.

## Consequences

- **Zero backend change for the whole editing surface.** No schema change, no
  propagation test, no migration.
- **The diff has to know the input's shape.** `config-diff.ts`, the section
  attribution, and the impact matchers all reference dotted paths through
  `UpdateDeploymentInput`. **Adding a config field means touching the diff
  walker and, if it can disrupt pods, the rule table** — otherwise the field
  changes silently with no diff entry and no impact line. This is the standing
  maintenance cost of client-side diffing, and it is a coupling the schema
  cannot enforce.
- **Impact text can be wrong without anything failing.** Nothing verifies a
  consequence string against real pod behaviour. Treat the table as
  documentation-grade, and never build gating logic on it.
- **The `parameters` merge asymmetry leaks into payload construction.** Every
  other field submits its complete current list; `parameters` merges server-side,
  so only changed parameters are included. The diff is display-only and is never
  used to build a partial payload for full-replacement fields.
- **The conflict window is narrow, not closed.** A concurrent write landing
  between the re-fetch and the mutation still wins silently. Closing it requires
  Strategy A.
- **Form-array normalisation needed a scoped tolerance.** TanStack Form
  normalises an unset array `defaultValues` to `[]` on first render, which would
  diverge from an `undefined` baseline and cause the reload-merge to treat an
  untouched field as edited. `conflictMerge.ts` tolerates exactly that one
  `undefined ↔ []` case and is deliberately not a general equality helper — an
  operator clearing a list to `[]` is a real edit.
- **Impact severity drives styling only.** `high` changes the dialog's colour and
  wording; it never disables Apply.

## Alternatives Considered

- **`just-diff` / `deep-object-diff` / `fast-json-patch`.** Rejected: all return
  positional array patches, so a reorder reads as a change, and none can
  attribute an entry to a UI section. Reshaping their output costs more than the
  purpose-built walk.
- **Inline impact logic in the dialog component.** Rejected: untestable in
  isolation and mixes presentation with policy.
- **A backend dry-run / `previewUpdateDeployment` in v1.** Explicitly out of
  scope; the rule table is built behind the interface that query will implement.
- **Backend-computed inheritance flags.** Rejected for v1: a schema change for
  data the client already has.
- **Long-polling or subscribing to the deployment from the open drawer.**
  Rejected: needs subscription infrastructure for a conflict rare enough that one
  synchronous check at apply time suffices.
- **Silent server-side last-write-wins.** Rejected outright by the spec.
- **`beforeunload` to guard unsaved edits.** Rejected: fires unreliably on tab
  close and conflates closing the drawer with closing the browser.
- **Masking env-var values behind a Reveal toggle.** Rejected: pretends the UI is
  a trust boundary it is not.
