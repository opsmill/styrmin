# Data Model: Ingress Class Set Only After the Chart Renders

**Feature**: [spec.md](spec.md) | **Research**: [research.md](research.md)

No new entity, database column, GraphQL type or driver-format field. No Alembic revision.

## Inputs the agent reads (unchanged)

| Field | Model | Meaning |
|-------|-------|---------|
| `instance.config.ingress_class` | `ResolvedConfig` ([`context/models/config.py`](../../backend/styrmin_backend/context/models/config.py)) | The resolved class: cluster config, then environment config, then deployment config, deepest wins. `traefik` when the cluster config does not set the key; `None` only when the cluster config sets `ingress_class: null` and no deeper level sets it. |
| `instance.config.dedicated_ingress` | `ResolvedConfig`, `DedicatedIngressConfig` | Any object, including `{}`, means the environment has a dedicated ingress controller. `None` means it has none. |
| `instance.config.dedicated_ingress.implementation` | `DedicatedIngressConfig` | The controller implementation; `traefik` by default and the only value today. |

## Ingress class rule: inputs to the Ingress the cluster receives

The rule applies to every Ingress in the release, including Ingresses from subcharts, whatever class the chart rendered.

| Mode | `dedicated_ingress` | Resolved `ingress_class` | `spec.ingressClassName` after post-render | `kubernetes.io/ingress.class` after post-render | Requirement |
|------|---------------------|--------------------------|-------------------------------------------|-----------------------------------------------|-------------|
| Dedicated | set | any value or `None` | absent | `dedicated_ingress.implementation` (`traefik`) | FR-002 |
| Shared | `None` | set, for example `nginx` | the resolved value | the resolved value | FR-001 |
| Shared, no class | `None` | `None` or empty | what the chart rendered | what the chart rendered | FR-006 |

## Patch blocks the ingress utility emits

All patches target `kind: Ingress` with no name, so they apply to every Ingress in the release. The other annotations of `AnnotationPatch` (router entrypoints, external-dns hostname, IP allow list middleware, endpoints type) do not change.

| Mode | `SpecPatch` (`ingressClassName`) | `kubernetes.io/ingress.class` in `AnnotationPatch` | `IngressClassNameRemovalPatch` (new) |
|------|----------------------------------|-----------------------------------------------------|--------------------------------------|
| Dedicated | not emitted | implementation | emitted |
| Shared | emitted with the resolved value | resolved value | not emitted |
| Shared, no class | not emitted | not set | not emitted |

### `IngressClassNameRemovalPatch` (new, `blocks/patches.py`)

A strategic merge patch block (research D-001). Subclass of `Patch`, like `RuntimeClassPatch`.

| Attribute | Default | Notes |
|-----------|---------|-------|
| `api_version` | `networking.k8s.io/v1` | Kustomize replaces it with the target resource's group and version. |
| `kind` | `Ingress` | |
| `name` | `any` | Required by Kustomize; not matched when a `target` is set. |
| `_path` | `/spec/ingressClassName` | For the `Patch` interface. |
| `_operation` | `remove` | For the `Patch` interface. |

`render_value()` returns:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: any
spec:
  ingressClassName: null
```

## Template data (changed)

`render_value_template` builds the Jinja data with `GlobalContext.model_dump(exclude_none=True)`. It no longer removes `ingress_class` from any section when `dedicated_ingress` is set (research D-004).

| Path | Before, dedicated mode | After, both modes |
|------|------------------------|-------------------|
| `instance.config.ingress_class` | absent | the resolved value (absent only when `None`) |
| `cluster.config.ingress_class` | absent | the cluster value |
| `environment.config.ingress_class` | absent | the environment value |
| `deployment.config.ingress_class` | absent | the deployment value |

## Example driver templates (changed)

| Driver | File | Change | `spec.version` |
|--------|------|--------|----------------|
| `simple-app` | `driver/examples/simple-app/values.j2.yml` | drop `className: "{{ instance.config.ingress_class }}"` | unchanged |
| `semaphore` | `driver/examples/semaphore/values.j2.yml` | drop the same line | unchanged |
| `slurpit` | `driver/examples/slurpit/values.j2.yml` | drop the same line | unchanged |

A reload of each driver creates a new driver version row with a new provenance fingerprint under the same `spec.version`.

## State transitions

None. Existing Ingresses change only when their application is next rendered, for example after a deploy, an upgrade, a config update or a config fan-out redeploy.
