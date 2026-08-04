# Data Model: Driver Detail Page Redesign (Tabbed Layout)

**Feature**: `012-driver-detail-tabs`
**Date**: 2026-05-21

This feature is a frontend redesign over an existing data surface, plus one additive GraphQL field. **No database schema or migration changes.** Below: the entities the page consumes, what changes, and what stays.

## Affected GraphQL Types

### `ApplicationDriver`

Source: `backend/styrmin_backend/api/definitions/application_driver/model.py:78`.

| Field | Type | Status | Notes |
|---|---|---|---|
| `id` | `UUID!` | unchanged | |
| `name` | `String!` | unchanged | |
| `versions` | `[ApplicationDriverVersion!]!` | unchanged | Resolver order unchanged; client sorts. |
| `createdOn` | `DateTime!` | **NEW** | Sourced from `ApplicationDriverModel.created_on` (`StyrminModel` base, non-null, `server_default = func.now()`). |

### `ApplicationDriverVersion`

Source: `backend/styrmin_backend/api/definitions/application_driver/model.py:101`.

| Field | Type | Status | Notes |
|---|---|---|---|
| `id` | `UUID!` | unchanged | |
| `applicationDriverId` | `UUID!` | unchanged | |
| `version` | `String!` | unchanged | Free-form version label. |
| `supportedVersions` | `String!` | unchanged | |
| `sourceType` | `String!` | unchanged | `"git"` or `"local"`. |
| `sourceRepository` | `String!` | unchanged | |
| `sourceBranch` | `String` | unchanged | Nullable. |
| `sourcePath` | `String` | unchanged | Nullable. |
| `components` | `JSON` | unchanged | Driver-declared component dict; shape per `driver/DRIVERS.md`. |
| `parameters` | `[ParameterDefinition!]!` | unchanged | |
| `componentConfigs` | `[ComponentConfig!]!` | unchanged | Not rendered in v1 (out of scope; the prior raw-JSON dump is removed). |
| `helmChart` | `HelmChart!` | unchanged | Rendered in Overview tab. |
| `actions` | `[Action!]!` | unchanged | |
| `createdOn` | `DateTime!` | **NEW** | Sourced from `ApplicationDriverVersionModel.created_on`. |

### Nested types consumed by the page (read-only, unchanged)

- **`HelmChart`** — `name`, `version`, `repository` rendered in Overview tab.
- **`ParameterDefinition`** — `name`, `label`, `kind`, `default`, `values` rendered as one Parameters tab row each. `required` derived as `default === null || default === undefined`.
- **`Action`** — `id`, `name`, `description`, `location` rendered as one Actions tab card each.

## Database Layer

**No changes.**

`ApplicationDriver` and `ApplicationDriverVersion` already inherit `created_on: datetime` from `StyrminModel` (`backend/styrmin_backend/db/models.py:32`). The column is non-null with a `server_default` of `func.now()`. The new GraphQL field is a thin resolver projection over this existing column.

No new tables, no new columns, no new indexes, no migration.

## Frontend Types

Generated TypeScript via `uv run invoke generate` (consumes `schema.graphql` + the updated `frontend/src/graphql/get_driver.graphql`). After regeneration, `useGetDriverQuery()` returns:

```ts
data?.applicationDriver?: {
  id: string;
  name: string;
  createdOn: string;   // ISO 8601 timestamp
  versions: Array<{
    id: string;
    version: string;
    supportedVersions: string;
    sourceType: string;
    sourceRepository: string;
    sourceBranch: string | null;
    sourcePath: string | null;
    components: unknown;          // JSON scalar
    parameters: ParameterFragment[];
    componentConfigs: ComponentConfigFragment[];
    helmChart: HelmChartFragment;
    actions: ActionFragment[];
    createdOn: string;
  }>;
}
```

## Derived state (page-local)

The page does not introduce new persisted state, but it does compute derived shapes from the query response:

- **Sorted versions**: `versions.toSorted((a, b) => Date.parse(b.createdOn) - Date.parse(a.createdOn))`. Drives the left rail order.
- **Selected version**: a local React `useState<string | null>(null)`. Initialised after first successful query to the first entry of the sorted list. Reconciled on every refresh per `EC-002` / `EC-003`.
- **Active tab**: a local React `useState<TabId>("overview")`. Preserved across version switches.
- **Components tab projection**: defensive iteration of `version.components`. For each `[componentName, componentDecl]` pair, extract `componentDecl.identifier?.label` (label dict) and any other scalar/dict properties for display. If `components` is not a plain object, render the empty state.

## Validation rules

This is a read-only view; no writes. The only validation is **defensive shape-checking** in the Components tab:

- `components` must be a plain object (`typeof === "object"`, not null, not an array). Otherwise → empty state.
- Each value within `components` must be a plain object. Otherwise that entry is skipped and not rendered.

## State transitions

None — the page does not transition any entity state.

## Open Questions

None.
