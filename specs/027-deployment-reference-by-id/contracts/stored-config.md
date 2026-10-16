# Contract: Stored Shape of a Deployment Reference

Applies to `environment.config`, `deployment.config` and `component.config` (see [data-model.md](../data-model.md)).

## Written

Either identifier is accepted, with the snake_case keys of the stored config (GraphQL inputs use `deploymentRef`, `deploymentId`, `deploymentName`):

```yaml
scheduling:
  pod_anti_affinity:
    preferred:
      - weight: 100
        term:
          topology_key: kubernetes.io/hostname
          deployment_ref:
            deployment_name: postgres        # or deployment_id: 7F0C…
            components: [primary]
```

## Stored and read back

```yaml
scheduling:
  pod_anti_affinity:
    preferred:
      - weight: 100
        term:
          topology_key: kubernetes.io/hostname
          deployment_ref:
            deployment_id: 7f0c2a3e-1b2c-4d5e-8f90-0a1b2c3d4e5f
            components: [primary]
```

Rules:

1. `deployment_name` is never stored (FR-003).
2. `deployment_id` is the canonical lowercase UUID string.
3. Every other key of the config is stored as written.
4. Writing back the read config is accepted and returns a null `Task` (FR-009). Re-sending the written form with the name, while the name still gives the same id, also returns a null `Task`.

## Resolved (`resolvedScheduling`, instance context, rendered pod template)

Unchanged from today:

```yaml
label_selector:
  match_labels:
    styrmin/deployment_id: 7f0c2a3e-1b2c-4d5e-8f90-0a1b2c3d4e5f
  match_expressions:
    - {key: styrmin/component, operator: In, values: [primary]}
```

## Error paths

| Where the term is | Path in the error |
| --- | --- |
| Environment config on `createEnvironment`, `updateEnvironment`, and at reconcile | `environment.config.scheduling.pod_anti_affinity.preferred[0].term` |
| Deployment config on `deploy`, `updateDeployment`, `updateDeploymentVersion`, and at reconcile | `deployment.config.scheduling.pod_affinity.required[1]` |
| Component config copied from the driver version | `component[server].config.scheduling.pod_affinity.required[0]` |
| Clone override | `config_override.scheduling.pod_affinity.required[0]` |
| Clone request check, deployment config of a source deployment | `deployment[api].config.scheduling.pod_affinity.required[0]` |
| Clone request check, component of a source deployment | `deployment[api].component[server].config.scheduling.pod_affinity.required[0]` |
