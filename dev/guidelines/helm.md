# Helm Chart Guidelines

Prescriptive rules for the Styrmin-owned Helm charts:

- `helm/styrmin/` — the platform chart (`styrmin-server`, `task-worker`, plus
  the `postgresql`, `prefect-server`, and `velero` subchart value overrides)
- `helm/agent/` — the `styrmin-agent` subchart

## Never configure resource limits

**Rule:** Styrmin's charts declare `resources.requests` only. They MUST NOT
ship `resources.limits` in default values, in templates, or in any values
file committed to this repo (`dev/local/demo-values.yaml`,
`backend/tests/e2e/fixtures/styrmin-values.yaml`, CI values, …).

This applies to every component the charts own *and* to the third-party
subchart sections nested in `helm/styrmin/values.yaml` — a limit injected via
`postgresql.primary.resources.limits` is still a limit Styrmin shipped.

### Why

- **A CPU limit throttles instead of bursting.** CFS quota enforcement stalls
  the container once the quota is spent within a period, even on an idle node.
  Styrmin's workloads are bursty by nature (reconcile loops, Helm renders,
  Prefect flow-run subprocesses) — the request already guarantees the
  scheduler reserves a floor, and bursting above it is exactly the behaviour
  we want.
- **A memory limit converts a transient spike into an OOM kill.** This is not
  hypothetical: capping `task-worker` memory is what turns a concurrent
  flow-run spike into a killed worker process, which is the failure mode
  behind [#312](https://github.com/opsmill/styrmin/issues/312) — a flow run
  orphaned in `PENDING`/`RUNNING` forever because the worker holding its claim
  died. Resource limits made that failure *more* likely, not less; the actual
  fix is the zombie-flow-run Automation registered by
  `PrefectManager.initialize()`.
- **Limits are a cluster-policy decision, not a chart default.** Sizing
  depends on node shape, overcommit tolerance, and whether the operator runs
  `LimitRange`/`ResourceQuota`. Baking a guess into the chart silently caps
  every install; leaving it out lets operators opt in deliberately.

### Operators can still set them

Nothing prevents an operator from adding limits in their own values file — the
templates render whatever `resources` map they are given. The rule is about
what Styrmin *ships as a default*, not about what the chart permits.

### Bitnami subcharts

Bitnami charts (e.g. `postgresql`) inject limits through `resourcesPreset`
unless an explicit `resources` map is provided. Setting `resources` with
`limits: {}` is how that preset is opted out of — keep the empty `limits: {}`
rather than deleting the key.

### Enforcement

`backend/tests/unit/test_helm_resource_limits.py` walks every `values.yaml`
under `helm/` (and the committed values overlays) and fails if any `limits`
key resolves to a non-empty mapping.

## Sizing requests

Requests should reflect the component's steady-state footprint, not its worst
case. Raise a request when the scheduler needs to reserve real headroom (as
`task-worker` does for flow-run subprocesses); do not raise it to "protect"
against a spike — that is what the absence of a limit already does.
