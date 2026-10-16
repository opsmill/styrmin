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

- A pod goes only to a node that matches at least one `required` term.
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
- The terms set on the environment and on the deployment are added
  together. To drop the environment's terms for one deployment, set
  `replace: true` in the deployment's `nodeAffinity` block.

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
