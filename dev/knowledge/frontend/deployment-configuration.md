<!-- Extracted from specs/011-unified-deployment-config on 2026-08-04 -->

## Deployment Configuration Surface

### Overview

Deployment configuration is read and edited through one surface: a **Configuration
tab** of read-only summary cards on the deployment detail page, and a right-side
**edit drawer** covering all eight config sections. This replaced a
scheduling-only modal, a raw JSON dump, and per-field edit affordances scattered
across the page.

The surface as introduced by 011 is client-side. There is no GraphQL schema change,
no new query, and no backend involvement beyond the existing `updateDeployment`
mutation — which has **full-replacement** semantics, so the UI is responsible for
showing the user what a submit will change before it fires. Component env vars are
the exception: they follow the backend's component container rule (see
[Component env vars follow the component container](#component-env-vars-follow-the-component-container)).

Design rationale and rejected alternatives:
[ADR-052](../../adr/0052-client-side-config-diff-impact-and-conflict-detection.md).

### File layout

```text
frontend/src/components/deployment/configuration/
├── ConfigurationTab.tsx        # read view: summary cards + Edit entry point
├── ConfigSummaryCard.tsx       # one card per section, with inheritance badge
├── ConfigEditDrawer.tsx        # the drawer: form instance, section nav, footer
├── SectionNav.tsx              # nav rail with per-section change dots
├── DrawerFooter.tsx            # pending-change count + Review & apply
├── ConfigDiffDialog.tsx        # diff + impact + conflict panel + Apply
├── DiffEntryRow.tsx            # one rendered DiffEntry
├── ImpactList.tsx              # rendered ImpactSummary
├── ChangedFieldFrame.tsx       # per-field "changed, was X" affordance
├── InheritanceBadge.tsx        # inherited / overridden badge
├── ParameterField.tsx          # shared driver-parameter renderer (also used by create)
├── ReplicasField.tsx           # per-component replica count field (also used by create)
├── conflictMerge.ts            # scoped equality helper for the reload-merge path
├── DeploymentContextDialog.tsx # resolved-context viewer
└── sections/
    ├── edit/                   # one editor per section (+ scheduling/ subtree)
    └── read/                   # one summary per section

frontend/src/lib/
├── configuration-types.ts      # SectionId, ConfigurationDraft, DiffEntry, ImpactRule, …
├── config-diff.ts              # structural diff → ConfigurationDiff
├── impact-rules.ts             # the declarative rule table
├── config-impact.ts            # rule evaluation → ImpactSummary
├── config-inheritance.ts       # per-section inherited / overridden state
├── effective-config.ts         # merged view of environment + deployment values
├── deployment-input.ts         # persisted config ↔ UpdateDeploymentInput transform (ADR-015)
└── replicas.ts                 # replica field check, placeholder and driver default
```

### The eight sections

`SectionId` is the single attribution key used by the diff, the impact rules, the
nav rail, and the summary cards:

`identity` · `driverParameters` · `scheduling` · `networking` · `envVars` ·
`storageRuntime` · `serviceOverrides` · `componentOverrides`

`SECTION_ORDER` in `configuration-types.ts` fixes nav order and the order of
`sectionsChanged`. The read view renders seven cards — Identity's non-editable
parts (driver, application version) live in the page header.

### Draft lifecycle

The drawer's working state is a `ConfigurationDraft`:

```ts
interface ConfigurationDraft {
  initial: UpdateDeploymentInput;      // frozen snapshot at mount; never mutated
  current: UpdateDeploymentInput;      // what TanStack Form binds to
  driverSchema: DriverParameterSchema; // ParameterDefinition[] from the pinned driver version
}
```

`initial` comes from `deploymentConfigToInput(deployment.config)` — the same
submit-boundary transform documented in
[ADR-015](../../adr/0015-frontend-value-transform-boundary.md). `initial` is both
the diff baseline and the source of every "was X" annotation.

**One TanStack Form instance for the whole drawer**, not one per section. That is
what lets the footer compute "N pending changes across M sections" without a
parent aggregator, and it keeps a single submit handler. Zod validators are
colocated per section. See
[`dev/guidelines/frontend/forms.md`](../../guidelines/frontend/forms.md).

```text
closed → open (idle) → open (dirty) → reviewing → applying → applied → closed
                            ↑              ↓
                            └── Back to edit
         open (dirty) + close attempt → confirming-discard → closed | open (dirty)
```

Closing while dirty raises an `AlertDialog` ("Discard pending changes?", default
Keep editing). There is no `sessionStorage` autosave — the drawer is a synchronous
workflow, and a resurrected draft on next open would surprise more than it saves.

### Diff → impact → apply

`config-diff.ts` walks `initial` against `current` once and returns:

```ts
interface ConfigurationDiff {
  entries: DiffEntry[];          // { section, path, label, before, after, kind }
  sectionsChanged: SectionId[];  // unique, in SECTION_ORDER
  hasChanges: boolean;
}
```

Paths are dotted, with **array entries keyed by stable identifier, never by
position**: `envVars[LOG_LEVEL]`, `tolerations[1].effect`,
`components[rate-limiter].resources.cpu.limit`, `scheduling.resources.cpu.request`.
Reordering env vars is therefore not a change — the property a generic diff
library cannot provide.

`impact-rules.ts` is an array of `{matcher, consequence, severity}`. Matchers glob
over the dotted path (`*` = one segment, `**` = many) with an optional `value:X`
qualifier for value-sensitive rules, e.g.
`scheduling.tolerations[*].effect value:NO_EXECUTE`. `config-impact.ts` evaluates
them into an `ImpactSummary` with deduplicated consequences and a `topSeverity`;
`topSeverity === "high"` flips the dialog into its disruptive treatment.

> **The rules are advisory and deliberately approximate.** They encode what we
> believe restarts pods and nothing verifies them against real behaviour. They
> style the dialog; they never gate or alter the mutation. **Adding a config field
> means updating `config-diff.ts` and — if the field can disrupt pods — the rule
> table**, or the field will change with no diff entry and no impact line.
> `config-impact.ts` is shaped so a future backend `previewUpdateDeployment` query
> can replace rule evaluation without changing the `ImpactSummary` consumers see.

Payload construction respects the `parameters` asymmetry from
[ADR-018](../../adr/0018-typed-update-deployment-input.md): full-replacement fields
always submit their complete current list, while `parameters` merges server-side so
only changed parameters are included. **The diff is display-only — it is never used
to assemble a partial payload.**

### Inheritance state

`config-inheritance.ts` compares the deployment's config against
`deployment.environment.config` (already selected by the existing `get_deployment`
query) and returns per-section:

```ts
type InheritanceState =
  | { kind: 'inherited' }
  | { kind: 'overridden'; overrideCount: number };
```

A section is *overridden* when at least one field differs from the environment's
value, or is set where the environment has none. Two special cases: **Driver
Parameters** has no environment equivalent, so it compares against the driver's
declared defaults; **Component Overrides** is inherited exactly when no
per-component block exists.

This drives the `InheritanceBadge` on each card and the drawer's "from X (env)"
per-field annotations.

### Concurrent edits

The drawer is a long-lived surface over a mutable row, so Apply re-checks before
mutating. `ConfigDiffDialog`:

1. Re-fetches `GetDeployment` in the foreground.
2. Hashes `{name, parameters, config}` on the refreshed row and compares against
   the same hash captured at drawer-open time.
3. **Unchanged** → dispatch `updateDeployment`, then invalidate `GetDeployment`.
4. **Changed** → render `ConflictPanel`; the mutation does not proceed.

Reload hands the refreshed deployment back to `ConfigEditDrawer`, which **swaps its
baseline to the new persisted state while keeping the user's pending edits**.
The draft is never discarded — only what it is measured against moves. There is no
"overwrite anyway" affordance.

Two caveats:

- **The window is narrow, not closed.** A write landing between the re-fetch and
  the mutation still wins silently. Closing it needs the deferred server-side
  path — expose the existing `Deployment.updated_on` column and return a typed
  `STALE_DEPLOYMENT_WRITE` error. That change can land without touching dialog
  code, because the same `ConflictPanel` path is driven by a typed error as
  readily as by a hash mismatch.
- **`conflictMerge.ts` exists for one normalisation quirk.** TanStack Form turns an
  unset array `defaultValues` into `[]` on first render, which would diverge from
  an `undefined` baseline and make the reload-merge treat an untouched field as
  edited. The helper tolerates exactly that `undefined ↔ []` case and is **not** a
  general equality helper — a user clearing a list to `[]` is a real edit.

### Env-var values are plaintext

Env-var values render in plaintext in both the summary card and the drawer,
matching what `View JSON`, the SDK, and the Kubernetes ConfigMap already expose.
The surface introduces no new exposure but does make the values more discoverable.
Masking behind a Reveal toggle was rejected: it would imply the UI is the trust
boundary when the GraphQL response carries the plaintext anyway. `EnvVar.value` is
documented as not being for secret material; a real secrets facility is a separate
workstream.

### Component env vars follow the component container

<!-- Extracted from specs/017-post-render-env-vars on 2026-10-02 -->

Styrmin injects env vars into each component's declared **component container**
([ADR-057](../../adr/0057-post-render-component-overrides.md)), and the backend
rejects added or changed component-scope env vars on a component without one
(`COMPONENT_CONTAINER_NOT_DECLARED`). The Components section of the drawer
(`ComponentOverridesSection.tsx`) mirrors that rule from `component.container`,
which `get_deployment.graphql` selects on `Deployment.components`:

- **Container declared**: the env var editor is unchanged.
- **No container**: no add or edit control is rendered. A component without a
  stored block shows one line (`component-override-no-container-<component>`)
  instead of **Add override**, so the drawer never creates an empty block for it.
  An explanation (`comp-env-no-container-<component>`) says the driver declares
  no container, so env vars can't be applied. A collapsed row that stores any
  value gets a **not applied** badge (`component-override-not-applied-<component>`). Stored values, typically left by a driver upgrade
  that dropped the container, render read-only (`component-env-var-readonly-row`)
  with a remove button, the same treatment as orphaned override blocks. Removing
  them submits a subset of the stored block, which the backend accepts.

Image overrides (018) follow the same rule. A component with a container gets an
**Image** input checked against `lib/image-reference.ts`. While any component's
reference is invalid, `DrawerDiffProvider` lists it and the footer disables
**Review & apply** with a hint naming the components. A component without a
container gets no input. A stored image renders read-only
(`comp-image-readonly-<component>`) with a **not applied** badge, the env var
explanation, and a remove button (`Remove image override for <component>`)
that sets `image` to `null`, which the backend accepts as a removal. Orphaned
blocks are removed whole, image included.

<!-- Extracted from specs/022-post-render-container-overrides on 2026-10-14 -->

Container `command` and `args` overrides (022) follow the same rule, because the
backend rejects adding or changing them on a component without a container
([ADR-069](../../adr/0069-container-command-args-by-post-render.md)). A component
with a container gets the **Command** and **Args** list editors
(`component-command-editor-<component>`, `component-args-editor-<component>`). A
component without one gets neither. Each editor is a labelled `group` described
by a hint, shows an empty state that says the chart's value applies, names each
input (`Command element <n> for <component>`, `Args element <n> for <component>`)
and warns under an empty command element, which the container would receive as
an empty string. A stored list on a component without a container renders
read-only as one JSON list in `ContainerlessContainerOverride`
(`comp-command-readonly-<component>`, `comp-args-readonly-<component>`), so
`["a b"]` and `["a", "b"]` read differently, with a **not applied** badge, the same
explanation, and a remove button (`Remove command override for <component>`,
`Remove args override for <component>`) that sets the list to `[]`. The submit
boundary (`componentsFormToInput` in `lib/deployment-input.ts`, called in
`ConfigDiffDialog.tsx`) leaves an empty list out of the input, which the backend reads as a removal.

`diffComponents` in `lib/config-diff.ts` compares `command` and `args` as well as
env vars and the image, and counts an empty list as no override. A change to only
`command` or `args` therefore produces a diff entry and enables **Review &
apply**.

The read summary (`ComponentOverridesSummary.tsx`) lists each stored `command`
and `args` as a JSON list (`component-container-override`) with an **applied** or
**not applied** badge from `Deployment.componentContainerOverrides.isApplicable`,
which `get_deployment.graphql` selects. Users who cannot open the drawer see the
values there. Orphan rows (`component-override-orphan-row`) cover every block
stored on an undeclared component, from `deployment.config.components`, the image
overrides and the container overrides, not only image overrides.

<!-- Extracted from specs/018-component-image-overrides on 2026-10-05 -->

Two read-only views show image overrides from `Deployment.componentImageOverrides`:

- **Read summary** (`ComponentOverridesSummary.tsx`): each declared component with
  an override gets an image line with the stored reference, the resolved one when
  `{{ app.version }}` makes them differ, and an **applied** or **not applied**
  badge from `isApplicable`. Overrides on components the driver no longer
  declares get their own row (`component-override-orphan-row`), badged
  **not applied**, also when the driver declares no components.
- **Upgrade dialog** (`PinnedImageOverridesNotice.tsx`, deployment detail page):
  before Confirm, lists every override that applies under the current driver
  version and has no `{{ app.version }}` token, with its reference. These
  components keep their image after the upgrade. The token check is
  `hasAppVersionToken` in `lib/image-reference.ts`.

The driver detail **Components** tab (`ComponentsTab.tsx`) shows each component's
container from `componentConfigs[].container`, or an explicit **None declared**
state with a tooltip, so driver authors can confirm what they declared.

Deployment- and environment-scope editors carry no such hint: those scopes skip
containerless components silently. Surfacing that in the UI is a deferred
follow-up (ADR-057 consequences); the API exposes it as
`ComponentEnvVars.isApplicable`.

### Replica overrides need no component container

<!-- Extracted from specs/023-per-component-replicas on 2026-10-15 -->

A replica override patches the component's workloads, not a container
([ADR-070](../../adr/0070-replica-overrides-and-retired-parameters.md)), so the
**Replicas** field shows on every component, with or without a container.
`ReplicasField.tsx` (`components/deployment/configuration/`) renders it in the
drawer and in the create form:

- A number input (`comp-replicas-<component>`, `aria-label="Replicas for
  <component>"`). Empty means no override. The placeholder names the count that
  applies without one, from `replicaPlaceholder` in `lib/replicas.ts`:
  `2 (driver default)` or `set by the chart`. `replicaDefault` takes the driver
  default from the `componentReplicas` row when its source is `DRIVER_DEFAULT`,
  and otherwise from the driver version's `componentConfigs[].replicas`, because
  the row's count is the override when the override is the source.
- `replicaFieldError` shows "Must be 1 or more. To run no pods, stop the
  component." below 1, and also rejects a non-integer and a value above
  2147483647 (`comp-replicas-error-<component>`). `componentOverridesSchema`
  runs the same check.
- A singleton component (`componentReplicas[].singleton`) gets a read-only input
  with the value `1 (singleton)`. A stored override above 1 on it renders in
  `SingletonReplicaOverride` (`comp-replicas-readonly-<component>`) with a
  **not applied** badge and a remove button (`Remove replica override for
  <component>`) that sets `replicas` to `null`, because the backend rejects
  resubmitting it. The collapsed row then shows the **not applied** badge too.

In the drawer, a component without a stored block shows the field above
**Add override**; typing a count creates the block. Clearing the field submits
`replicas: null` when a value is stored, and leaves the field `undefined`
otherwise, so typing and clearing is not a change. The submit boundary
(`componentsFormToInput`) turns an empty field into `null`, and `diffComponents`
compares `components[<name>].replicas` with `null` and `undefined` as equal.
`get_deployment.graphql` selects `componentReplicas` and
`componentConfigs { replicas }` of the pinned driver version. The
`FutureExtensionPlaceholder` line lists CPU and memory only.

The create form (`DeployFormPage.tsx`) has a **Component replicas** section
(`component-replicas-section`) that lists the components of the selected driver
version from `componentConfigs { name replicas singleton }`, with the same
field. It sends `config.components` with only the components that have a value,
and blocks the submit with an error naming the components whose count is
invalid.

The read summary (`ComponentOverridesSummary.tsx`) gets `componentReplicas` from
`ConfigurationTab.tsx` and shows a replica line (`component-replicas`, with
`data-source`, `data-applicable` and `data-stopped`) under every declared
component: `3 (override)`, `2 (driver default)`, `1 (driver default, singleton)`
or `set by the chart`; `override N` and a **not applied** badge when a stored
override does not apply; an **applied** badge when it does; and
`stopped: 0 pods` when `components[].enabled` is `false`. An orphaned override
shows as `N (override)` with a **not applied** badge in its orphan row.

### Testing

Section editors carry Vitest component tests alongside them. Behavioural coverage
is `[ui-chromium]`-only E2E under `backend/tests/e2e/configuration/`, marked
`@pytest.mark.ui_only` — the SDK could call `updateDeployment` directly, so an
`[api-chromium]` variant would exercise none of this surface. Each test seeds a
deployment, opens the tab, edits a section, verifies the diff entries, applies,
and asserts the persisted config (and, where relevant, that pods restarted).
