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

## Velero subchart naming

**Rule:** the `velero` subchart section of `helm/styrmin/values.yaml` MUST keep
`fullnameOverride: velero`, and no committed values overlay may change it.

### Why

Velero's repository-maintenance controller resolves **its own Deployment by the
hardcoded name `velero`** in the Velero namespace
(`pkg/repository/maintenance/maintenance.go`, `buildJob`) to copy the image,
env, volumes, and service account into the kopia maintenance Job. The name is
not configurable in Velero.

The subchart's default fullname is `<release>-velero`, so without the override
every maintenance cycle fails:

```text
level=warning msg="error pruning repository" error="error to build maintenance
job: Deployment.apps \"velero\" not found"
```

The failure is invisible from the outside: backups and restores keep working,
but kopia never prunes, so the data behind expired backups is never reclaimed
and the bucket grows without bound. Velero also does not back off — a failed
cycle is appended to `status.recentMaintenance` without stamping
`status.lastMaintenanceTime`, so the warning repeats on every 5-minute reconcile
of every `BackupRepository`.

### What the name pins

Pinning the fullname also makes the subchart's resource names independent of the
Helm release name. `VELERO_RESTORE_PVC_PATCH_CONFIGMAP` in
`agent/service/kubernetes/resources/builders/backup.py` depends on that: the
chart renders `configMaps` entries as `<fullname>-<key>`, and every Velero
Restore Styrmin builds points `spec.resourceModifier` at that ConfigMap by name.
Rename either side alone and Velero rejects every restore.

### Enforcement

`backend/tests/unit/test_helm_velero_naming.py` asserts the override, the
ConfigMap name agreement, and that no overlay re-points the fullname.
`test_backup_and_restore_lifecycle` (E2E, `shard_backup`) forces a maintenance
cycle on the repository a real backup wrote to and fails if Velero cannot
complete it.

## Read values that a chart upgrade adds with `dig`

<!-- Extracted from specs/020-backend-telemetry on 2026-10-10 -->

[CLAUDE RECOMMENDED – based on the telemetry Helm values of spec 020 (contracts/configuration.md,
code review finding 4 of 2026-10-10)] When a chart version adds a nested value, read it in
templates through a helper in `_helpers.tpl` that uses `dig` with the default, not as
`.Values.a.b.c`.

### Why

`helm upgrade --reuse-values` reuses the values stored with the release and does not merge in
the new chart's `values.yaml`. A release installed from a chart version without the new map has
no such map, so `.Values.styrmin.telemetry.enabled` failed to render with
`nil pointer evaluating interface {}.enabled`. `dig` returns the default instead.

```yaml
{{- define "styrmin.telemetry.endpoint" -}}
{{- dig "telemetry" "endpoint" "" .Values.styrmin -}}
{{- end }}
```

### Booleans that the server also reads

An operator can set a boolean with `--set-string`, which gives the template the string `"false"`.
In a template condition a non-empty string is true, while the server reads `"false"` as false,
so the install notes and the server would disagree. A helper that renders such a value accepts
the strings the server accepts (`true`, `1`, `t`, `y`, `yes`, `on`, `false`, `0`, `f`, `n`, `no`,
`off`, in any case), returns `"true"` or `"false"`, and stops the render with `fail` on any other
value. See `styrmin.telemetry.enabled` in `helm/styrmin/templates/_helpers.tpl`.

### Enforcement

`backend/tests/unit/test_helm_telemetry_values.py` renders the chart with the values of a
release that has no `styrmin.telemetry` map, as `--reuse-values` gives it.

## Reconcile cadence for third-party controllers

`velero server` defaults `--backup-sync-period` and
`--store-validation-frequency` to 1m. Each cycle spawns and then kills a
`velero-plugin-for-aws` process, and the teardown trips an open upstream bug
that logs, at error level, a spurious
`error encountered while scanning stdout ... read |0: file already closed`
([velero#7892](https://github.com/vmware-tanzu/velero/issues/7892)). At the
default cadence that is ~7 lines/minute of noise per BSL, which buries the logs
that matter during a real backup.

`helm/styrmin/values.yaml` therefore sets both to `5m`. Styrmin names the BSL
explicitly on every `Backup` and tracks backup state in its own database, so it
never depends on fast BSL revalidation or on Velero's bucket sync. Prefer
slowing a third-party reconcile loop over dropping the log level: `logLevel:
warning` would also hide the lines a real backup failure needs.

## Sizing requests

Requests should reflect the component's steady-state footprint, not its worst
case. Raise a request when the scheduler needs to reserve real headroom (as
`task-worker` does for flow-run subprocesses); do not raise it to "protect"
against a spike — that is what the absence of a limit already does.
