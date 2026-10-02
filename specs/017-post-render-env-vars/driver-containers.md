# Driver Component Containers (T001)

**Feature**: 017-post-render-env-vars | **Date**: 2026-10-02 | **Feeds**: T019, T027, T034–T039

## Overview

Every in-repo example driver chart was rendered with `helm template` using its driver's own
`values.j2.yml`. For each component, the identifier selector was matched against the rendered
`Deployment` and `StatefulSet` resources, and the container to declare as
`components.<name>.container` was read off the matched pod template. This pins research D-010
against real renders (critique E4).

**Result**: all 28 components match exactly one workload, and every matched workload carries the
container research D-010 names. No component is flagged. The spec artifacts say "30 components";
the real count is 28 (2 + 3 + 7 + 7 + 1 + 2 + 6).

## Component Containers

The selector is the one the platform builds: the first identifier label as `key=value`
(`LabelIdentifier.label_selectable()`, `context/models/components.py`), matched against
`metadata.labels` the way a Kustomize `target.labelSelector` is. Env patches target only `Deployment`
and `StatefulSet` (research D-001).

| Driver | Component | Identifier selector | Kind | Matched workload | Container |
|---|---|---|---|---|---|
| simple-app | server | `app.kubernetes.io/name=simple-app` | Deployment | `styrmin-simple-app` | `simple-app` |
| simple-app | database | `app.kubernetes.io/name=postgresql` | StatefulSet | `styrmin-postgresql` | `postgresql` |
| db-test | server | `app.kubernetes.io/name=db-test` | Deployment | `styrmin-db-test` | `db-test` |
| db-test | mariadb | `app.kubernetes.io/name=mariadb` | StatefulSet | `styrmin-db-test-mariadb` | `mariadb` |
| db-test | mongodb | `app.kubernetes.io/component=mongodb` | Deployment | `styrmin-db-test-mongodb` | `mongodb` |
| infrahub | server | `service=infrahub-server` | Deployment | `styrmin-infrahub-infrahub-server` | `infrahub-server` |
| infrahub | task-worker | `service=infrahub-task-worker` | Deployment | `styrmin-infrahub-infrahub-task-worker` | `infrahub-task-worker` |
| infrahub | database | `infrahub/service=database` | StatefulSet | `styrmin-database` | `neo4j` |
| infrahub | cache | `infrahub/service=cache` | StatefulSet | `styrmin-cache-master` | `redis` |
| infrahub | message-queue | `infrahub/service=message-queue` | StatefulSet | `styrmin-message-queue` | `rabbitmq` |
| infrahub | task-manager | `app.kubernetes.io/name=prefect-server` | Deployment | `styrmin-task-manager` | `prefect-server` |
| infrahub | task-manager-db | `infrahub/service=task-manager-db` | StatefulSet | `styrmin-postgresql` | `postgresql` |
| infrahub-enterprise | server | `service=infrahub-server` | Deployment | `styrmin-infrahub-infrahub-server` | `infrahub-server` |
| infrahub-enterprise | task-worker | `service=infrahub-task-worker` | Deployment | `styrmin-infrahub-infrahub-task-worker` | `infrahub-task-worker` |
| infrahub-enterprise | database | `infrahub/service=database` | StatefulSet | `styrmin-database` | `neo4j` |
| infrahub-enterprise | cache | `infrahub/service=cache` | StatefulSet | `styrmin-cache-master` | `redis` |
| infrahub-enterprise | message-queue | `infrahub/service=message-queue` | StatefulSet | `styrmin-message-queue` | `rabbitmq` |
| infrahub-enterprise | task-manager | `app.kubernetes.io/name=prefect-server` | Deployment | `styrmin-task-manager` | `prefect-server` |
| infrahub-enterprise | task-manager-db | `infrahub/service=task-manager-db` | StatefulSet | `styrmin-postgresql` | `postgresql` |
| infrahub-mcp | server | `app.kubernetes.io/name=infrahub-mcp` | Deployment | `styrmin-infrahub-mcp` | `infrahub-mcp` |
| semaphore | server | `app.kubernetes.io/name=semaphore` | Deployment | `styrmin-semaphore` | `semaphore` |
| semaphore | database | `app.kubernetes.io/name=postgresql` | StatefulSet | `styrmin-postgresql` | `postgresql` |
| slurpit | portal | `app.kubernetes.io/component=portal` | Deployment | `styrmin-slurpit-portal` | `slurpit-portal` |
| slurpit | warehouse | `app.kubernetes.io/component=warehouse` | Deployment | `styrmin-slurpit-warehouse` | `styrmin-slurpit-warehouse` |
| slurpit | scanner | `app.kubernetes.io/component=scanner` | Deployment | `styrmin-slurpit-scanner` | `slurpit-scanner` |
| slurpit | scraper | `app.kubernetes.io/component=scraper` | Deployment | `styrmin-slurpit-scraper` | `slurpit-scraper` |
| slurpit | mariadb | `app.kubernetes.io/component=mariadb` | Deployment | `styrmin-slurpit-mariadb` | `slurpit-mariadb` |
| slurpit | mongodb | `app.kubernetes.io/component=mongodb` | Deployment | `styrmin-slurpit-mongodb` | `styrmin-slurpit-mongodb` |

Each matched workload has exactly one container, so a declared container never lands on the wrong
container. No other `Deployment`/`StatefulSet` in any render matches a component selector, and no
chart renders a `Job`, `CronJob`, or `DaemonSet`.

Init containers on matched workloads, which env patches leave untouched (research D-001):

| Driver | Workload | Init containers |
|---|---|---|
| simple-app | `styrmin-simple-app` | `wait-for-postgresql` |
| db-test | `styrmin-db-test` | `wait-for-mariadb`, `wait-for-mongodb` |
| db-test | `styrmin-db-test-mariadb` | `preserve-logs-symlinks` |
| db-test | `styrmin-db-test-mongodb` | `log-dir` |
| infrahub, infrahub-enterprise | `styrmin-message-queue` | `prepare-plugins-dir` |
| semaphore | `styrmin-semaphore` | `admin` |

None of these init containers receives user env vars today either (see the sentinel check below),
so no in-repo driver loses env on an init container after migration.

## How It Was Rendered

### Values

`values.j2.yml` is Jinja, so each one was rendered first with the backend's own environment
(`get_jinja_environment(undefined=SilentUndefined)` from
`agent/service/kubernetes/resources/builders/application.py`, the same call
`render_value_template` makes), then `yaml.safe_load`-ed and written to
`values/<driver>.values.yaml`. The rendering context:

| Key | Value |
|---|---|
| `app.version` | simple-app, db-test `0.1.0`; infrahub, infrahub-enterprise `1.5.0`; infrahub-mcp `1.1.0`; semaphore `2.16.47`; slurpit `1.3.6` |
| `parameters` | each driver's parameter defaults; infrahub-mcp `infrahub_address=http://infrahub.example:8000` (no default) |
| `services[<name>]` | `primary_fqdn=<name>.example.test`, `human_readable_fqdn=<name>-hr.example.test` for each declared service, plus `slurpit` (the template references it undeclared) |
| `instance.config` | `ingress_class=nginx`, `standard_storage.storage_class=standard`, `fast_storage.storage_class=standard`, `external_url_scheme=https`, `external_url_port=443` |
| `components` | each driver component as `{config: <driver definition>}`, no env vars or overrides, so the filters render `[]` |

`fullnameOverride` comes straight from each template: `styrmin-simple-app`, `styrmin-db-test`,
`styrmin-infrahub` (under `infrahub:` for enterprise), `styrmin-infrahub-mcp`, `styrmin-semaphore`,
`styrmin-slurpit`. Subchart overrides in the same templates (`styrmin-postgresql`,
`styrmin-database`, `styrmin-task-manager`, `styrmin-cache`, `styrmin-message-queue`,
`styrmin-db-test-mariadb`, `styrmin-db-test-mongodb`) render as-is. The infrahub `commonLabels`
that lift `infrahub/service` onto subchart `StatefulSet` metadata are part of the rendered values,
so the `cache`, `message-queue`, and `task-manager-db` matches depend on them.

### Charts

Local charts were copied out of the repo before `helm dependency build`, so the worktree was not
modified. simple-app's `postgresql-16.7.27.tgz` is committed; db-test's dependencies are not.

```bash
cp -r driver/examples/simple-app/src/helm charts/simple-app/helm
cp -r driver/examples/db-test/src/helm charts/db-test/helm
helm dependency build charts/db-test/helm   # mariadb 25.0.5, mongodb 18.6.19 (bitnami)
```

### Commands

`helm` v4.1.0. Release name `styrmin` and namespace `styrmin-demo` are arbitrary; every workload
name comes from a `fullnameOverride`, so neither affects the names above.

```bash
# simple-app (local chart 0.1.0)
helm template styrmin charts/simple-app/helm -n styrmin-demo -f values/simple-app.values.yaml

# db-test (local chart 0.1.0)
helm template styrmin charts/db-test/helm -n styrmin-demo -f values/db-test.values.yaml

# infrahub (sha256:9d369b250694bed1bd596e4e49a199af1555a020ff0c463e7ee554ce6530ea4b)
helm template styrmin oci://registry.opsmill.io/opsmill/chart/infrahub --version 4.33.2 \
  -n styrmin-demo -f values/infrahub.values.yaml

# infrahub-enterprise (sha256:6b5fd03d2ee251e87f7809e05cd0411bddc4b8602c679851ef3f008e5339413f)
helm template styrmin oci://registry.opsmill.io/opsmill/chart/infrahub-enterprise --version 4.19.2 \
  -n styrmin-demo -f values/infrahub-enterprise.values.yaml

# infrahub-mcp (sha256:b4f9363ba9ea3c31669f3516c09437fa6d188ecad6e616506ea789ae633ae9b2)
helm template styrmin oci://registry.opsmill.io/opsmill/chart/infrahub-mcp --version 0.1.0 \
  -n styrmin-demo -f values/infrahub-mcp.values.yaml

# semaphore
helm template styrmin semaphore --repo https://semaphoreui.github.io/charts --version 16.0.11 \
  -n styrmin-demo -f values/semaphore.values.yaml

# slurpit (sha256:6474e4bb9d5ada1ac4fd0d1635622ee1b00bee1e3fe723d86eb81e17adb7e345)
helm template styrmin oci://registry.opsmill.io/external/slurpit --version 1.3.6 \
  -n styrmin-demo -f values/slurpit.values.yaml
```

All seven renders exited 0. The slurpit render prints `cannot overwrite table with non table` for
`slurpit.{portal,warehouse,scanner,scraper,mariadb,mongodb}.env` (see the findings below).

### Sentinel Check

To confirm the declared container is the one that receives env vars today, every component got a
`T001_SENTINEL_<COMPONENT>=x` env var through the current `component_env_vars` wiring, and each
driver was re-rendered with the same commands. The sentinel landed:

| Driver | Where `T001_SENTINEL_*` landed |
|---|---|
| simple-app | `simple-app` and `postgresql` container `env` |
| db-test | `db-test`, `mariadb`, and `mongodb` container `env` |
| infrahub, infrahub-enterprise | container `env` of `infrahub-server`, `infrahub-task-worker`, `prefect-server`, `redis`, `rabbitmq`, `postgresql`; neo4j via the `styrmin-database-env` ConfigMap (consumed by `envFrom`) |
| infrahub-mcp | nowhere; the template has no env wiring today |
| semaphore | `postgresql` container `env` only; the `server` sentinel is dropped |
| slurpit | nowhere usable: every sentinel lands as a mangled ConfigMap entry |

Wherever a sentinel reached a container, it reached the container in the table above, and never an
init container or a second container.

## Findings

These do not change any container name. They affect the migration tasks.

1. **slurpit env wiring is broken today (pre-existing).** The slurpit 1.3.6 chart expects each
   `<component>.env` as a map and copies it into a `<fullname>-<component>-config` ConfigMap with
   `range $key, $value`, consumed through `envFrom`. Since c4927f9 the driver passes a
   `[{name, value}]` list, so the ConfigMap gets keys `0`, `1`, … with values like
   `map[name:PORTAL_DB_HOSTNAME value:...]`, and the chart's default env map is replaced. Neither
   the hard-coded wiring (DB host, credentials, warehouse tokens) nor user env vars reach the
   containers. T037 should restore the map shape for the hard-coded entries when it removes the
   `component_env_vars` loops. Post-render env patches work on these containers: `env` entries win
   over `envFrom`.
2. **semaphore `server` never received user env vars (pre-existing).** The semaphore 16.0.11 chart
   has no `extraEnv` key; its env slots are `extraEnvVariables` / `extraEnvSecrets` (maps) and
   `envFromSecrets` / `envFromConfigMaps`. The driver's `extraEnv:` line is ignored. Migration
   removes it, and post-render injection onto `semaphore` fixes the gap.
3. **infrahub `database` (neo4j) user env goes through a ConfigMap today.** The chart renders
   `neo4j.env` into `styrmin-database-env` and loads it with `envFrom`; the `neo4j` container also
   carries its own chart `env` entries (`HELM_NEO4J_VERSION`, `POD_NAME`, `SERVICE_NEO4J*`, …). A
   post-render patch merges into that `env` list by name and wins over `envFrom` for the same name,
   so chart defaults survive and same-name entries are overridden as FR-002 requires.
4. **Component count.** plan.md, tasks.md, and alignment-check.md say 30 components; there are 28.
