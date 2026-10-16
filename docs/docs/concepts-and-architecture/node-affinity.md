---
title: Node affinity
sidebar_position: 7
description: Place a deployment's pods on nodes by node label.
---

## Node affinity

Node affinity places a deployment's pods on nodes whose labels match.
You set it in the `scheduling.nodeAffinity` value of a deployment or an
environment. Styrmin adds it to the pods after the chart renders.

### Where you can set it

- **On a deployment**, for that deployment's pods:
  - In the web UI, open the deployment, select the **Settings** tab,
    click **Update Settings**, and go to **Scheduling** >
    **Node affinity**.
  - With the `updateDeployment` GraphQL mutation,
    `styrminctl deployments update`, or `spec.config.scheduling` in a
    `deployments apply` manifest (see
    [Manifest `spec.config` shape](../reference/styrminctl.md#manifest-specconfig-shape)).
- **On an environment**, for every deployment in it, with the
  `updateEnvironment` GraphQL mutation. The environment page shows the
  value but cannot change it.
- **Not on a cluster.** Styrmin ignores a cluster's `scheduling` value,
  so there is no cluster-wide node affinity. See
  [#482](https://github.com/opsmill/styrmin/issues/482).

`updateDeployment`, `styrminctl deployments update` and
`updateEnvironment` replace the whole config: a value that the request
leaves out is cleared. Send the current config with the new `scheduling`
value.

### How terms match nodes

- The `required` terms set on one environment or one deployment are
  alternatives: a pod goes only to a node that matches at least one of
  them.
- A `preferred` term has a `weight` from 1 to 100. The scheduler places
  the pod on a matching node when it can, and on another node when it
  cannot.
- A term's `labelSelector` matches node labels:
  - Each `matchLabels` entry becomes an `In` expression.
  - `matchExpressions` take the operators `IN`, `NOT_IN`, `EXISTS` and
    `DOES_NOT_EXIST`.
  - A node must match every label in one term. To require two labels,
    put both in the same term, not in two terms.
- The API requires a `topologyKey` on every term, but node affinity
  ignores it. Set it to an empty string.

### When the environment and the deployment both set terms

- When both set `required` terms, a pod goes only to a node that matches
  one of the environment's terms and one of the deployment's terms.
  Styrmin puts each environment term together with each deployment term
  into one term on the pod.
- The `preferred` terms of the environment and the deployment are added
  together.
- To drop the environment's terms for one deployment, set
  `replace: true` in the deployment's `nodeAffinity` block.

For example, the environment requires `pool=apps`, and the deployment
requires `zone=a` or `zone=b`:

```json
{ "scheduling": { "nodeAffinity": { "required": [
  { "topologyKey": "", "labelSelector": { "matchLabels": { "pool": "apps" } } }
] } } }
```

```json
{ "scheduling": { "nodeAffinity": { "required": [
  { "topologyKey": "", "labelSelector": { "matchLabels": { "zone": "a" } } },
  { "topologyKey": "", "labelSelector": { "matchLabels": { "zone": "b" } } }
] } } }
```

Styrmin adds two terms to the pods, so a node must have `pool=apps` and
one of the two zones:

```yaml
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - {key: pool, operator: In, values: [apps]}
            - {key: zone, operator: In, values: [a]}
        - matchExpressions:
            - {key: pool, operator: In, values: [apps]}
            - {key: zone, operator: In, values: [b]}
```

The `resolvedScheduling` field of a deployment in the GraphQL API shows
these combined terms.

### When running deployments get the combined terms

Styrmin used to add each term of each level to the pods as its own term,
so a node that matched only the environment's terms or only the
deployment's terms was accepted
([#486](https://github.com/opsmill/styrmin/issues/486)). A deployment
that already runs keeps the terms it was rendered with until Styrmin
redeploys it. Styrmin redeploys a deployment, and gives its pods the
combined terms, when:

- you update or upgrade the deployment, or stop or start its components.
- you change the config of its environment. Styrmin redeploys the
  deployments of the environment, even when the change is to an
  unrelated value.
- you update its cluster, even when the update changes an unrelated
  value. Styrmin redeploys each deployment whose resolved config
  changed, and the combined terms change the resolved config of every
  deployment where the environment and the deployment both set
  `required` terms and the deployment does not set `replace: true`.

Before you update a cluster, list the deployments that the update
redeploys: run `styrminctl clusters update` with `--dry-run`, send
`updateCluster` with `dryRun: true`, or open the **Edit** dialog on the
cluster detail page, which lists them before it saves. A deployment
whose terms cannot be met together with the environment's terms has
pods that stay pending after this redeploy.

### If pods stay Pending

A pod stays `Pending` when no node matches its required terms. This
happens when the environment's terms and the deployment's terms cannot
be met together. For example, the environment requires `pool=apps` and
the deployment requires `pool=db`: a node has one value for a label, so
no node matches both. Styrmin saves this config without a warning.

What you view:

- The deployment's **Pods** tab shows the pods as `PENDING`, without the
  reason. To read why the scheduler did not place a pod, expand the pod,
  open **Commands**, and run the **Events** or the **Describe** command.
  The `FailedScheduling` event says that the nodes didn't match the
  pod's node affinity.
- The deployment becomes `FAILED` when its pods are not ready within the
  readiness timeout, and FluxCD rolls the release back at the HelmRelease
  timeout. See
  [When a rollout is ready or failed](operator-and-crds.md#when-a-rollout-is-ready-or-failed)
  for both timeouts.

To fix it, do one of the following:

- To use only the deployment's terms, set `replace: true` in the
  deployment's `nodeAffinity` block and update the deployment.
- With `updateEnvironment`, change the environment's terms so that they
  accept the nodes that the deployment needs, for example with the
  expression `pool` `IN` `apps`, `db`. Styrmin then redeploys the
  deployments of the environment.

### Replacing a node selector

Styrmin no longer accepts `node_selector` on a cluster or a deployment,
because it stored the value but never applied it to a pod
([#472](https://github.com/opsmill/styrmin/issues/472)). To place a
deployment's pods on nodes labelled `pool=apps`, replace the old value
with a required node affinity term.

Before, in the deployment config (no pod received it):

```json
{ "nodeSelector": "pool=apps" }
```

After:

```json
{
  "scheduling": {
    "nodeAffinity": {
      "required": [
        {
          "topologyKey": "",
          "labelSelector": { "matchLabels": { "pool": "apps" } }
        }
      ]
    }
  }
}
```

Styrmin adds this affinity to the pods:

```yaml
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - key: pool
              operator: In
              values: [apps]
```

In the web UI, go to **Scheduling** > **Node affinity**, click
**Add required term**, then **Add expression**, and enter the key
`pool`, the operator `IN` and the value `apps`.

If the value was set on a cluster, set it on each environment or
deployment that needs it.
