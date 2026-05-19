# Quickstart — Hierarchical Pod Scheduling & Resource Configuration

This walkthrough shows a platform operator configuring the new `scheduling` section at each level, inspecting the resolved effective configuration, and verifying the rendered pod specs on a real cluster. It assumes the Styrmin backend, Prefect agent, and kopf operator are running, with at least one cluster and one environment available. Commands are illustrative — GraphQL mutations can be sent via the Styrmin CLI (`uv run styrmin …`) or any GraphQL client.

## 0. Preconditions

- A cluster registered in Styrmin with a working vcluster/E2E setup (see `tests/integration/operator/README.md`).
- An environment (`dev`) in that cluster.
- An application driver registered whose spec declares two components: `server` and `worker`.
- A tainted node pool on the cluster: `dedicated=batch:NoSchedule` (for Story 3 validation).
- A sandboxed `RuntimeClass` named `kata` installed on the cluster (for Story 4 validation). The platform no longer validates the name against the cluster — any DNS-1123 string is accepted. If the `RuntimeClass` resource is missing the pod goes Pending with a scheduler error.

## 1. Set environment-wide defaults (US2, US3)

Set default CPU/memory requests and limits plus a toleration for the `batch` node pool at the environment level so that every deployment in `dev` inherits them.

```graphql
mutation {
  updateEnvironment(
    environmentId: "<dev-env-uuid>"
    config: {
      scheduling: {
        resources: {
          requests: { cpu: "100m", memory: "256Mi" }
          limits:   { cpu: "500m", memory: "512Mi" }
        }
        tolerations: [
          { key: "dedicated", operator: "Equal", value: "batch", effect: "NoSchedule" }
        ]
      }
    }
  ) { id name }
}
```

**Expected**: mutation succeeds with no validation error. Any deployment created in `dev` now inherits these values for every component.

## 2. Create a first deployment (US1 — "all components on one node")

Deploy application A with a pod-affinity rule that binds every component of the deployment onto the same node.

```graphql
mutation {
  createDeployment(
    environmentId: "<dev-env-uuid>"
    name: "app-a"
    config: {
      scheduling: {
        pod_affinity: {
          required: [{
            topology_key: "kubernetes.io/hostname"
            deployment_ref: { deployment_name: "app-a" }
          }]
        }
      }
    }
  ) { id name }
}
```

**Expected**: the resolver expands `deployment_ref` into a label selector matching the deployment's own `styrmin/deployment_id` label. On rollout, the pods of `server` and `worker` land on the same node.

## 3. Create a second deployment with a cross-deployment anti-affinity (US1 — avoid a peer)

Deploy application B such that its pods never land on a node already running `app-a`.

```graphql
mutation {
  createDeployment(
    environmentId: "<dev-env-uuid>"
    name: "app-b"
    config: {
      scheduling: {
        pod_anti_affinity: {
          required: [{
            topology_key: "kubernetes.io/hostname"
            deployment_ref: { deployment_name: "app-a" }
          }]
        }
      }
    }
  ) { id name }
}
```

**Expected**: on rollout, every pod of `app-b` lands on a node that is NOT currently running any `app-a` pod.

## 4. Override a single component's resource request (US2)

Bump `worker`'s CPU request without touching `server`.

```graphql
mutation {
  updateComponent(
    componentId: "<app-a-worker-component-uuid>"
    config: {
      identifier: { label: { "app.myorg/service": "app-a-worker" } },
      scheduling: {
        resources: { requests: { cpu: "2" } }
      }
    }
  ) { id name }
}
```

**Expected**: `worker`'s rendered pod spec now has `cpu: 2` (deepest-level-wins for scalars). `memory` request/limit and `cpu` limit continue to inherit from the environment defaults. `server` remains unchanged.

## 5. Sandbox the worker with a runtime class (US4)

Apply a sandboxed runtime to `worker` only.

```graphql
mutation {
  updateComponent(
    componentId: "<app-a-worker-component-uuid>"
    config: {
      identifier: { label: { "app.myorg/service": "app-a-worker" } },
      scheduling: {
        resources: { requests: { cpu: "2" } },
        runtime_class: "kata"
      }
    }
  )
}
```

**Expected**: only `worker` pods launch under `runtimeClassName: kata`. Names that reference a `RuntimeClass` not installed on the cluster pass validation but the pod stays `Pending` with a scheduler error until the `RuntimeClass` is created.

## 6. Opt out of post-render injection for resources on a single component (FR-016)

Hand resources back to the Helm chart for `server` because the chart already wires them from Helm values, while keeping the post-renderer responsible for the other features.

```graphql
mutation {
  updateComponent(
    componentId: "<app-a-server-component-uuid>"
    config: {
      identifier: { label: { "app.myorg/service": "app-a-server" } },
      scheduling: {
        inject: { resources: false }
      }
    }
  )
}
```

**Expected**: the post-renderer no longer patches `server`'s `resources`. The resolved values are still exposed in `GlobalContext` so the driver template can place them itself if desired. All other scheduling features continue to be injected.

## 7. Inspect the resolved effective configuration (US5, SC-004)

```graphql
query {
  deployment(id: "<app-a-uuid>") {
    id
    name
    resolvedScheduling {
      componentName
      config
      provenance
    }
  }
}
```

**Expected response (abridged)**:

```json
{
  "deployment": {
    "resolvedScheduling": [
      {
        "componentName": "server",
        "config": {
          "pod_affinity": { "required": [{ "topology_key": "kubernetes.io/hostname", "label_selector": { "match_labels": { "styrmin/deployment_id": "<app-a-uuid>" } } }] },
          "resources": { "requests": { "cpu": "100m", "memory": "256Mi" }, "limits": { "cpu": "500m", "memory": "512Mi" } },
          "tolerations": [{ "key": "dedicated", "operator": "Equal", "value": "batch", "effect": "NoSchedule" }],
          "inject": { "resources": false }
        },
        "provenance": {
          "pod_affinity.required[0]": "deployment",
          "resources.requests.cpu": "environment",
          "resources.requests.memory": "environment",
          "resources.limits.cpu": "environment",
          "resources.limits.memory": "environment",
          "tolerations[0]": "environment",
          "inject.resources": "component"
        }
      },
      {
        "componentName": "worker",
        "config": {
          "pod_affinity": { "required": [{ "topology_key": "kubernetes.io/hostname", "label_selector": { "match_labels": { "styrmin/deployment_id": "<app-a-uuid>" } } }] },
          "resources": { "requests": { "cpu": "2", "memory": "256Mi" }, "limits": { "cpu": "500m", "memory": "512Mi" } },
          "tolerations": [{ "key": "dedicated", "operator": "Equal", "value": "batch", "effect": "NoSchedule" }],
          "runtime_class": "kata"
        },
        "provenance": {
          "resources.requests.cpu": "component",
          "resources.requests.memory": "environment",
          "runtime_class": "component"
        }
      }
    ]
  }
}
```

## 8. Verify the rendered pod specs on the cluster (US6)

After the next reconciliation, inspect the actual Deployments produced by FluxCD:

```bash
kubectl -n <app-a-namespace> get deploy -l styrmin/deployment_id=<app-a-uuid> -o yaml
```

**Expected**:
- Both `server` and `worker` pod specs carry `tolerations[0] = {key: dedicated, ...}`.
- Both pod specs carry the pod-affinity term with `labelSelector.matchLabels.styrmin/deployment_id = <app-a-uuid>`.
- `server`'s `resources` field reflects the Helm chart's own values (post-renderer opted out for resources on this component).
- `worker`'s `resources.requests.cpu = 2` and `runtimeClassName: kata`.
- On `app-b`'s pods, the pod-anti-affinity `labelSelector.matchLabels.styrmin/deployment_id` points at `<app-a-uuid>`.

## 9. Failure modes you can reproduce

- **Unknown component**: submit component-level scheduling for a name the driver did not declare → `UnknownComponentInConfigError` (VALIDATION_ERROR) (FR-005).
- **Unresolvable deployment_ref**: reference a deployment that does not exist in the environment → `UnresolvableAffinityReferenceError` (FR-001d).
- **Invalid quantity**: set `resources.requests.cpu = "two"` → Pydantic validation fails with a clear `path` (`scheduling.resources.requests.cpu`).
- **Non-existent runtime class**: set `runtime_class = "ghost"` → the mutation succeeds, FluxCD applies the pod spec, and the pod goes `Pending` with a scheduler `RuntimeClassNotFound` error (no pre-apply rejection — the allow-list check was removed).
- **Unsatisfiable affinity**: define anti-affinity against a deployment that already occupies every node → pods remain `Pending` and the deployment status surfaces the unsatisfied constraint with its source level (FR-018).

## 10. What "done" looks like

A successful run of this quickstart against a real vcluster covers acceptance scenarios for all six user stories (US1 through US6). It is the same scenario exercised by `tests/integration/operator/test_pod_scheduling_e2e.py`; if the quickstart passes by hand, the E2E test should too.
