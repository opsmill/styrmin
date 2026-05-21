# Contract — Section component prop interface

**Status**: Internal contract. Defines the prop shape every section component (read summary + drawer edit) must adhere to. Establishes a uniform pattern so all 7 read summaries and 8 edit sections feel consistent and can be added/removed by file.

## Read summary component (`sections/read/<Section>Summary.tsx`)

```ts
export interface SectionSummaryProps {
  /** Persisted deployment configuration (already projected through deploymentConfigToInput). */
  current: UpdateDeploymentInput;
  /** Parent environment configuration, projected the same way. Used to render inherited values in muted style. */
  environment: UpdateDeploymentInput;
  /** Driver parameter schema — required only by DriverParametersSummary, optional elsewhere. */
  driverSchema?: DriverParameterSchema;
  /** Computed inheritance state for this section. Drives the badge. */
  inheritance: InheritanceState;
}
```

**Behaviour**:
- Renders the summary card shell (title + badge) via `<ConfigSummaryCard title={...} inheritance={...}>...</ConfigSummaryCard>`.
- Body content varies per section but always uses the same visual tokens: `Inter` for labels, `JetBrains Mono` for technical values, `#1d4ed8` for overridden values, `#9ca3af` italic for inherited values.
- No interactive controls except an outer "Edit configuration" CTA handled by `<HeroSummaryBar>`.

## Edit section component (`sections/edit/<Section>Section.tsx`)

```ts
export interface SectionEditProps {
  /** TanStack Form instance scoped to the whole drawer; sections bind to their own sub-paths. */
  form: ReactForm<UpdateDeploymentInput>;
  /** Initial values snapshot for "from X" annotations. */
  initial: UpdateDeploymentInput;
  /** Parent environment values for "from X (env)" annotations. */
  environment: UpdateDeploymentInput;
  /** Required by DriverParametersSection / ServiceOverridesSection / ComponentOverridesSection. */
  driverSchema?: DriverParameterSchema;
  /** Anchor id used by the section nav rail's scroll-spy. */
  anchorId: SectionId;
}
```

**Behaviour**:
- Renders an `<h3>` section heading with anchor id matching `anchorId`.
- Renders a "N changed" chip next to the heading when at least one field within the section is dirty (compute via `form.useStore(state => countSectionChanges(state, anchorId))`).
- All field inputs are wrapped in `<ChangedFieldFrame field={...} initial={...} environment={...}>` so dirty state, "from X" annotations, and amber border treatment are uniform.
- Per-section Zod schema is exposed via a named export (`schedulingSchema`, `envVarsSchema`, …) for unit tests and for the drawer's aggregated `Form.validate()`.

## Why this contract matters

- Each slice adds one matched pair (read summary + edit section). Reviewers know exactly which prop shape to expect.
- Component Overrides is a first-class peer; it implements the same interface, with its body being a list of collapsible per-component blocks (one `<ChangedFieldFrame>` per editable field per component).
- The contract is internal, but documenting it here makes slice-PR reviews mechanical: "Does the new section export both `<XSummary>` and `<XSection>`? Do their props match these signatures? Does it have a `xSchema` export?"
