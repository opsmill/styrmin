# Post-Render Patch and Driver Format Contract

## Driver specification file

```yaml
spec:
  components:
    server:
      container: simple-app          # NEW, optional: the component container
      identifier:
        label:
          app.kubernetes.io/name: simple-app
```

- One name per component in v1. Omit it and the component accepts no component-scope env vars.
- The name must match a container in every `Deployment` / `StatefulSet` the identifier label
  selects; otherwise the Helm release fails on the next reconcile that injects env vars.

## Values template

- `component_env_vars` is retired: calling it fails rendering with `RETIRED_TEMPLATE_FILTER`.
- `instance.config.env_vars` and `components[<name>].env_vars.config` remain readable (e.g. to
  build a ConfigMap); writing them into a chart env key reintroduces the list-replacement problem
  and is discouraged by the guide.
- `component_command` / `component_args` are unchanged.

## Rendered patch

For component `task-manager` (container `prefect-server`, identifier
`app.kubernetes.io/name=prefect-server`) with resolved env vars
`{"LOG_LEVEL": "debug", "PROMETHEUS_MULTIPROC_DIR": "/data"}`, the HelmRelease gains two
entries at the **end** of `spec.postRenderers[0].kustomize.patches`:

```yaml
- target:
    kind: Deployment
    labelSelector: app.kubernetes.io/name=prefect-server
  patch: |
    apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: any
    spec:
      template:
        spec:
          containers:
          - name: prefect-server
            env:
            - name: LOG_LEVEL
              value: debug
              valueFrom: null
            - name: PROMETHEUS_MULTIPROC_DIR
              value: /data
              valueFrom: null
- target:
    kind: StatefulSet
    labelSelector: app.kubernetes.io/name=prefect-server
  patch: |
    # same body with kind: StatefulSet
```

## Rendered result (verified, kustomize v5.7.1)

Chart container env `[PREFECT_UI_SERVE_BASE=/, PROMETHEUS_MULTIPROC_DIR=/tmp]` becomes:

```yaml
env:
- name: LOG_LEVEL
  value: debug
- name: PROMETHEUS_MULTIPROC_DIR
  value: /data
- name: PREFECT_UI_SERVE_BASE
  value: /
```

Guarantees:

- Chart entries not named by the patch are kept, in chart order, after the user's entries.
- Same-name entries are replaced, including `valueFrom` entries.
- The component container becomes `containers[0]`; other containers and `initContainers` are
  untouched; `Job` / `CronJob` / `DaemonSet` are never targeted.
- No patch is emitted for a component with no container or no resolved env vars.
- Output is deterministic for a given resolved config.
