import type { ParameterDefinition } from "@/generated/graphql";

/**
 * One of the eight sections shown in the unified Configuration drawer's
 * nav rail. Every diff entry, inheritance computation, and impact rule
 * is attributed to exactly one `SectionId`.
 *
 * See `specs/011-unified-deployment-config/data-model.md`.
 */
export type SectionId =
  | "identity"
  | "driverParameters"
  | "scheduling"
  | "networking"
  | "envVars"
  | "storageRuntime"
  | "serviceOverrides"
  | "componentOverrides";

/**
 * Ordered list of section ids — drives section-nav ordering and `sectionsChanged`.
 *
 * Ordering rationale: environment-shaped concerns (env vars, service-name
 * overrides) come before parameter/driver knobs; scheduling lives at the bottom
 * as the advanced / disruptive section. Identity stays first because it carries
 * the deployment's primary identifier.
 */
export const SECTION_ORDER: readonly SectionId[] = [
  "identity",
  "envVars",
  "serviceOverrides",
  "driverParameters",
  "networking",
  "storageRuntime",
  "componentOverrides",
  "scheduling",
] as const;

/**
 * Section groups rendered by the edit drawer (and its left nav rail). Unlike
 * {@link SECTION_ORDER} — which is the data-model order used by the diff
 * helper, the inheritance helper, and the read view — this constant is a
 * UI-only structure that:
 *
 *  1. **Excludes Networking.** That section remains in the read view (Settings
 *     tab) so operators can still inspect inherited values, but is not
 *     currently editable through the drawer. Re-introduce it by adding its
 *     `SectionId` back into a group when the editing flow is restored.
 *
 *     Storage & Runtime *is* included, but its editor covers only
 *     `backupTtl` (016-backup-retention-ttl). `dbSize`,
 *     `standardStorage.storageClass`, and `nodeSelector` stay read-only on the
 *     Settings tab — see `StorageRuntimeSection`.
 *  2. **Names two visible groupings** — "Global settings" and "Components" —
 *     to distinguish deployment-wide knobs from component-scoped ones.
 *  3. **Treats Identity as its own un-labelled group** so the deployment-name
 *     anchor sits cleanly at the top of the drawer.
 *
 * The `label: null` convention means "no visible group header"; only the
 * section(s) render. Otherwise the label is rendered as a small uppercase
 * heading both in the nav rail and the form body.
 */
export interface DrawerSectionGroup {
  id: "identity" | "global" | "components";
  label: string | null;
  sectionIds: readonly SectionId[];
}

export const DRAWER_SECTION_GROUPS: readonly DrawerSectionGroup[] = [
  { id: "identity", label: null, sectionIds: ["identity"] },
  {
    id: "global",
    label: "Global settings",
    sectionIds: [
      "envVars",
      "serviceOverrides",
      "driverParameters",
      "storageRuntime",
      "scheduling",
    ],
  },
  {
    id: "components",
    label: "Components",
    sectionIds: ["componentOverrides"],
  },
] as const;

/**
 * Inheritance status of a section relative to its parent environment.
 *
 * - `inherited`: every field in the section matches the environment-derived value.
 * - `overridden`: the section sets `overrideCount` deployment-level overrides.
 */
export type InheritanceState =
  | { kind: "inherited" }
  | { kind: "overridden"; overrideCount: number };

/** One of three kinds of diff entries. */
export type DiffKind = "add" | "remove" | "change";

/**
 * A field-level difference between two `UpdateDeploymentInput` snapshots,
 * attributed to its owning section.
 */
export interface DiffEntry {
  section: SectionId;
  /**
   * Dotted path inside `UpdateDeploymentInput`. Array entries use stable
   * keys (env-var name, toleration key, component name) so order-only
   * changes do not appear in the diff.
   */
  path: string;
  /** Human label rendered in the Review dialog. */
  label: string;
  /** Stringified previous value, empty string for `add`. */
  before: string;
  /** Stringified new value, empty string for `remove`. */
  after: string;
  kind: DiffKind;
}

/**
 * Diff result returned by `diff(before, after, driverSchema)`.
 */
export interface ConfigurationDiff {
  entries: DiffEntry[];
  /** Unique, in section nav order. */
  sectionsChanged: SectionId[];
  hasChanges: boolean;
}

/** Severity ladder used by the impact heuristic and the Review dialog. */
export type ImpactSeverity = "informational" | "warning" | "high";

/**
 * Declarative impact rule. Evaluated against each `DiffEntry`.
 *
 * Glob syntax (applied to `DiffEntry.path`):
 *  - `.` segment separator
 *  - `*` matches a single path segment
 *  - `**` matches zero or more segments
 *  - `[*]` matches any array key segment
 *
 * Optional space-separated suffix qualifiers:
 *  - `value:X` — only fires when `DiffEntry.after === "X"`
 *  - `kind:add` / `kind:remove` / `kind:change` — only fires for that change kind
 */
export interface ImpactRule {
  matcher: string;
  consequence: string;
  severity: ImpactSeverity;
}

/** One de-duplicated consequence entry in the `ImpactSummary`. */
export interface ImpactEntry {
  consequence: string;
  severity: ImpactSeverity;
  /** Subset of `DiffEntry.path` values that produced this entry. */
  triggeringPaths: string[];
}

/**
 * Aggregate of impact rule firings. `topSeverity = "high"` flips the
 * Review dialog into its disruptive treatment.
 */
export interface ImpactSummary {
  entries: ImpactEntry[];
  topSeverity: ImpactSeverity;
}

/**
 * TS alias for the driver-defined parameter schema. The GraphQL surface
 * returns this as `applicationDriverVersion.parameters: ParameterDefinition[]`;
 * we re-alias it here so the configuration libraries can take a single
 * named type rather than re-importing `ParameterDefinition[]` everywhere.
 */
export type DriverParameterSchema = readonly ParameterDefinition[];
