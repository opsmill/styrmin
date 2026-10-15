# Contract: SDK, `styrminctl` and Frontend

**Feature**: [../spec.md](../spec.md) | Research: [D-010](../research.md#d-010-sdk-and-styrminctl), [D-011](../research.md#d-011-frontend)

## SDK

- Regenerated `ComponentConfigInput` has `replicas: int | None`.
- `get_deployment.graphql` selects `componentReplicas { component count source override singleton isOrphaned isApplicable }`.
- `get_driver*.graphql` operations that select `componentConfigs` add `replicas singleton`.
- `OverrideKind` gains `"replicas"`. `ApplyOutcome.inapplicable_overrides` lists a stored replica override with `isApplicable: false`.

## `styrminctl deployments apply` manifest

```yaml
apiVersion: styrmin/v1
kind: Deployment
metadata:
  name: my-infrahub
spec:
  driver: infrahub
  version: "1.5.0"
  config:
    components:
      - name: task-worker
        replicas: 4
```

No CLI code: `_Spec.config` is validated against the regenerated input types. Applying the same manifest twice changes nothing (`action="unchanged"`), because the server's no-op check compares instances.

## `styrminctl deployments get`

The Components table gains a `Replicas` column:

| Row | `Replicas` cell |
|-----|-----------------|
| Override applied | `3 (override)` |
| Driver default | `2 (driver default)` |
| Singleton, no override | `1 (driver default, singleton)` |
| Chart | `chart` |
| Stopped component | the resolved value followed by `, stopped: 0 pods` (for example `3 (override), stopped: 0 pods`) |
| Orphaned override | extra row: `3 (override, not applied: no longer declared)` |

## Frontend

| Surface | Behaviour |
|---------|-----------|
| Edit drawer, per component | "Replicas" number field (`aria-label="Replicas for <component>"`, `data-testid="comp-replicas-<component>"`). Placeholder shows the value that applies without an override: `2 (driver default)` or `set by the chart`. Empty field = no override. Below 1: "Must be 1 or more. To run no pods, stop the component." |
| Edit drawer, singleton component | Read-only field showing `1 (singleton)`. A stored override above 1 shows with a remove button only. |
| Create form | "Component replicas" section listing the selected driver version's components with the same field; sends `config.components` only for components with a value. |
| Configuration view | "Replicas" line per component: `3 (override)`, `2 (driver default)`, `set by the chart`; "not applied" badge when `isApplicable` is false; "stopped: 0 pods" when the component is stopped; orphaned rows as for other overrides. |
| Driver version page, Components tab | "Replicas" row (`not set` when null) and "Singleton" row (`yes` / `no`). |
| Upgrade dialog | Unchanged; shows the `RETIRED_PARAMETER_VALUE` or `SINGLETON_REPLICA_OVERRIDE` message on a rejected change. |
| Edit drawer placeholder | The "coming in future iterations" note no longer lists replicas; it keeps CPU and memory. |
