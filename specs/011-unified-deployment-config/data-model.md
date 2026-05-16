# Data Model — Unified Deployment Configuration Surface

**Feature**: 011-unified-deployment-config
**Phase**: 1 (design)

This feature is frontend-only. The data model below describes **client-side** types that live under `frontend/src/lib/` and back the section components and dialogs. There is no database, no GraphQL schema change, no new persistence.

Where a type derives from the GraphQL schema, the generated TypeScript type from `pnpm codegen` is the source of truth and we reference it rather than redefine it.

---

## Generated types (reused, not redefined)

| Type | Source | Purpose |
|---|---|---|
| `UpdateDeploymentInput` | `frontend/src/graphql/__generated__/...` | The mutation input shape. Used as the drawer form's domain model. |
| `Deployment` | `frontend/src/graphql/__generated__/...` | The GraphQL `Deployment` type — includes `config: JSON`, `parameters: [ParameterValue!]`, `environment: Environment`, etc. |
| `Environment` | `frontend/src/graphql/__generated__/...` | The parent environment record — `config: JSON`. Used to compute inheritance. |
| `DriverParameterSchema` | `frontend/src/graphql/__generated__/...` | Driver-defined parameter declarations — names, types, defaults, descriptions. Drives Driver Parameters renderers. |
| `Task` | `frontend/src/graphql/__generated__/...` | Used to surface "last changed" hero summary line (most recent successful `update_deployment` task). |

---

## New client-side types

### `SectionId`

```ts
export type SectionId =
  | 'identity'
  | 'driverParameters'
  | 'scheduling'
  | 'networking'
  | 'envVars'
  | 'storageRuntime'
  | 'serviceOverrides'
  | 'componentOverrides';
```

Used everywhere the feature needs to attribute a value, a diff entry, or an impact rule to one of the 8 sections shown in the drawer's nav rail. The read view groups Identity into the page header (driver/app version are not editable in the drawer's Identity section beyond `name`) and uses the remaining 7 as summary cards on the Configuration tab.

---

### `InheritanceState`

```ts
export type InheritanceState =
  | { kind: 'inherited' }
  | { kind: 'overridden'; overrideCount: number };
```

One per section. Computed by `lib/config-inheritance.ts` from the deployment config + parent environment config. Drives the badge on each summary card and (in the drawer) the per-field "from X (env)" annotation for fields whose draft value still equals the environment-inherited default.

---

### `ConfigurationDraft`

The drawer's working state — the persisted deployment config (projected through `deploymentConfigToInput()`) plus any pending edits made inside the drawer.

```ts
export interface ConfigurationDraft {
  initial: UpdateDeploymentInput;     // snapshot at form mount; never mutated
  current: UpdateDeploymentInput;     // edited shape; what the diff compares against `initial`
  driverSchema: DriverParameterSchema; // needed for Driver Parameters validation + read display
}
```

**Lifecycle**:
- Mounted when the drawer opens.
- `current` is what TanStack Form binds to.
- Diff is `diff(initial, current, driverSchema)` — computed on demand when "Review & apply" is clicked (and continuously for the section nav rail's change dots and the footer's pending-count).
- Discarded (`current ← initial`) by the Discard action or by confirming "Discard pending changes?" on drawer close.

---

### `ConfigurationDiff`

The output of `lib/config-diff.ts`. Represents the field-level differences between `initial` and `current`, attributed to sections.

```ts
export interface ConfigurationDiff {
  entries: DiffEntry[];
  sectionsChanged: SectionId[];        // unique, in section nav order
  hasChanges: boolean;                 // entries.length > 0
}

export interface DiffEntry {
  section: SectionId;
  /**
   * Dotted path inside `UpdateDeploymentInput`. Examples:
   *   "name"
   *   "scheduling.resources.cpu.request"
   *   "envVars[LOG_LEVEL]"
   *   "tolerations[1].effect"
   *   "components[rate-limiter].resources.cpu.limit"
   *
   * Array entries use stable keys (env var name, toleration key, component name)
   * — never positional indices — so order-only changes do not appear in the diff.
   */
  path: string;
  /** Human label rendered in the dialog (e.g., "CPU request", "Toleration effect"). */
  label: string;
  /** Stringified previous value, empty string for add. */
  before: string;
  /** Stringified new value, empty string for remove. */
  after: string;
  kind: 'add' | 'remove' | 'change';
}
```

---

### `ImpactRule`

Declarative entry in `lib/impact-rules.ts`. Evaluated by `lib/config-impact.ts` against a `ConfigurationDiff` to produce an `ImpactSummary`.

```ts
export interface ImpactRule {
  /**
   * Glob-style matcher on DiffEntry.path.
   *   "*"   matches a single path segment
   *   "**"  matches any number of segments
   *   "value:X" qualifier matches when DiffEntry.after === "X" (e.g., toleration effect → NoExecute)
   *
   * Examples:
   *   "name"
   *   "scheduling.resources.**"
   *   "tolerations[*].effect value:NoExecute"
   */
  matcher: string;
  /** Consequence text rendered in the dialog's Impact section. */
  consequence: string;
  severity: 'informational' | 'warning' | 'high';
}
```

---

### `ImpactSummary`

```ts
export interface ImpactSummary {
  entries: ImpactEntry[];
  topSeverity: 'informational' | 'warning' | 'high';
}

export interface ImpactEntry {
  /** Deduplicated consequence label drawn from one or more rule firings. */
  consequence: string;
  severity: 'informational' | 'warning' | 'high';
  /** Subset of DiffEntry.path values that produced this entry — used for "this consequence comes from these changes" tooltips. */
  triggeringPaths: string[];
}
```

`topSeverity = 'high'` flips the dialog into the disruptive (amber) treatment shown in the Paper mock.

---

### `UpdateEventSummary`

Powers the hero summary's "Last changed" line.

```ts
export interface UpdateEventSummary {
  timestamp: string;          // ISO 8601
  actor: string;              // email or service account
  summary: string;            // e.g., "scheduling resources"
}
```

**Source**: derived client-side from the deployment's most recent successful `update_deployment` task in the existing Timeline data, OR (preferred follow-up) a new `Deployment.lastUpdateEvent` field on the GraphQL schema. See research R-009. V1 ships with the client-derived fallback; the field-based approach is a non-blocking follow-up.

---

### `ChangedFieldMarker`

Per-field UI state used by `<ChangedFieldFrame>`:

```ts
export interface ChangedFieldMarker {
  isChanged: boolean;
  /** Stringified original value (from `ConfigurationDraft.initial`). */
  originalValue: string | null;
  /**
   * True when the original value came from the environment (inherited), not from
   * an explicit deployment-level setting. Drives "from X (env)" suffix.
   */
  fromEnvironment: boolean;
}
```

---

## Validation rules

Each section's Zod schema is colocated with the section component. Rules summarized below — full Zod schemas live in code.

| Section | Key rules |
|---|---|
| Identity | `name`: 1–64 chars, lowercase, kebab-case (matches existing deployment-name regex). |
| Driver Parameters | Per-parameter: matches `DriverParameterSchema[name].type`. Required parameters must have a value (string non-empty, number not NaN, select within enum). Unknown parameters (not in schema) flagged as invalid (driver schema drifted). |
| Scheduling | CPU/memory: matches Kubernetes quantity regex (e.g., `^\d+(m|Mi|Gi|...)?$`). Tolerations: `key` non-empty when `operator=Equal`. Topology spread `maxSkew >= 1`. Runtime class: matches Kubernetes name regex. |
| Networking | `fqdnSuffix`: valid DNS suffix. `externalUrlPort`: 1–65535. `ipWhitelist[*]`: valid CIDR (IPv4 or IPv6). `ingressClass`: matches Kubernetes name regex. |
| Env Vars | `name`: matches POSIX env var name regex. Unique within the list. |
| Storage & Runtime | `dbSize`: enum (`small | medium | large | xlarge`). `standardStorage.storageClass`: non-empty Kubernetes name. `nodeSelector`: parses to valid label selector expression. |
| Service Overrides | `driverServiceName`: must reference a service declared by the driver. `overrideName`: matches Kubernetes service-name regex (RFC 1035), unique within the list. |
| Component Overrides | Component name must reference a driver-declared component. Per-component resources follow the same quantity regex as Scheduling. |

---

## State transitions

### Drawer lifecycle

```text
closed → opening (animate-in)
       → open (idle)
       → open (dirty)             ← any field edited
       → reviewing                 ← "Review & apply" clicked
         → applying                ← "Apply & redeploy" clicked
           → applied (success)     ← mutation resolves → close everything, refresh tab
           → error                 ← stay in reviewing, show server error
         → open (dirty)            ← "Back to edit"
       → confirming-discard        ← close attempted while dirty
         → closed                  ← Discard confirmed
         → open (dirty)            ← Keep editing
       → closed                    ← Discard action OR close attempted while clean
```

### Configuration tab refresh after apply

```text
applied → urql cache invalidated (deployment query)
        → Configuration tab re-renders with new persisted values
        → inheritance state recomputed
        → InheritanceBadge re-renders per section
```

---

## Notes on backwards compatibility

- `UpdateDeploymentInput` already has full-replacement semantics for everything except `parameters` (merge). The diff library handles this asymmetry by treating `parameters` specially when computing the input payload: when only some parameters changed, only the changed ones are included in the input list (relying on the backend's merge semantics).
- For full-replacement fields with array values (e.g., `envVars`, `ipWhitelist`, `tolerations`, `components`), the form always submits the complete current list. The diff is only used for display, not to construct partial inputs.
- This guarantees the existing backend semantics (per the `UpdateDeploymentInput` GraphQL docstring) are preserved.
