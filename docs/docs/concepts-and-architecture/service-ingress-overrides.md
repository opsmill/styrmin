---
title: Service ingress overrides
sidebar_position: 6
description: Publish one external service of a deployment with another ingress class and another FQDN suffix than the rest of the deployment.
---

## Service ingress overrides

A deployment publishes all of its services with the ingress class and the
FQDN suffix that Styrmin resolves for it: the deployment's value, else the
environment's, else the cluster's. A **service ingress override** sets another
ingress class, another FQDN suffix, or both, for one external service of one
deployment. The other services of the deployment keep the resolved values.

An operator uses an override to publish the administration interface of an
application differently from its web interface. The case that led to this
feature was a task manager that answered a health request without a login on
the public address of a sandbox deployment, because Styrmin applied one
ingress class to every Ingress of the deployment
([#598](https://github.com/opsmill/styrmin/issues/598)).

An override applies to a service that its driver declares `scope: external`.
For these services, Styrmin builds the Ingress itself: see
[The Ingress that Styrmin builds for an external service](./ingress-and-networking.md#the-ingress-that-styrmin-builds-for-an-external-service).

### What an override changes

Take the task manager of an `infrahub` deployment in the environment `lab`,
on a cluster with the ingress class `traefik` and the FQDN suffix
`example.com`. You set the class `tailscale` and the suffix
`tailnet.example.ts.net` for the service `task-manager`:

| | Without the override | With the override |
|---|---|---|
| Ingress class | `traefik` | `tailscale` |
| Readable host | `task-manager-lab.example.com` | `task-manager-lab.tailnet.example.ts.net` |
| Application address on this Ingress | none: the first service of `infrahub` is `infrahub`, and it is internal | none |
| Annotations that Styrmin sets | the Traefik entry points, the external-dns host name, the Cloudflare setting, the class | the class only |

The end-to-end test of this feature checked the following on a disposable
vCluster with a dedicated Traefik ingress controller, where the override class
was `tailscale` and the suffix was `tailnet.example.ts.net`:

- The `task-manager` Ingress changed its class and host. It stayed the same
  Kubernetes object: its `uid` did not change.
- The Ingress that the chart renders for the `infrahub` service did not change.
  Its `resourceVersion` was the same before and after, so Kubernetes did not
  write to it.
- After the override was cleared, the `task-manager` Ingress had the original
  class, host and annotations again.

The rules in detail:

- **Each field is optional.** A field that you leave empty uses the resolved
  value. An override with both fields empty is no override: Styrmin does not
  store it.
- **The Ingress carries the class and no other Styrmin annotation.** It has
  `spec.ingressClassName` and the annotation `kubernetes.io/ingress.class`, both
  set to the override class. It has no Traefik entry-point annotation, no
  external-dns annotation, no Cloudflare annotation and no allow-list
  annotation. This holds when only the suffix is overridden: the Ingress is
  then an overridden Ingress, with the resolved class and no other annotation.
  This is read in the code that builds the Ingress. The end-to-end test
  overrides both fields.
- **The override suffix applies to the readable host only.** The application
  address `<driver name>-<deployment id>.<fqdn suffix>` keeps the resolved
  suffix. An overridden Ingress never has it, so the service that carries the
  application address keeps it only without an override.
- **An override class replaces the rule for a dedicated ingress controller.**
  In an environment with a dedicated ingress controller, an Ingress without an
  override has no `spec.ingressClassName`, and its class annotation names the
  controller. An Ingress with an override class has the override class in both
  fields instead. The end-to-end test runs on such an environment: the other
  Ingresses kept their class and annotations, and the overridden one had the
  override class.
- **A driver template reads the new host.** `services['<name>'].human_readable_fqdn`
  has the override suffix. The `infrahub` drivers use it for the address that the
  Prefect UI calls, and the test checked that the address followed the
  override. See [The context](../drivers/context.md).
- **Services that have no override do not change.** Overriding one service
  leaves the other Ingresses of the deployment as they were.

### What an override does not do

- **It does not apply `ip_whitelist`.** The allow list of a deployment is a
  reference to a Traefik middleware in the annotations of an Ingress. An
  overridden Ingress has no such annotation, so `ip_whitelist` does not restrict
  the overridden service, whatever the class. Restrict access in the ingress
  controller that serves the override class, outside Styrmin.
- **It does not write `spec.tls`.** Styrmin writes no `spec.tls` on an
  Ingress that it builds.
- **It does not install or check the controller.** The controller that serves
  the override class, for example the Tailscale operator, must already run in
  the cluster. Styrmin does not install it and does not check that it exists.
- **It does not open the network path.** Network access for the pods of that
  controller to the service is arranged outside Styrmin, for example with a
  network policy. This was verified for a shared Traefik on a local kind
  cluster, and not for Tailscale proxy pods.
- **It does not exist at the cluster or environment level.** An override is
  stored on one deployment, for one service. There is no rule that matches
  services by name across drivers.
- **It does not add annotations.** An overridden Ingress carries no extra
  annotations, so it cannot point a service at a second Traefik
  ([#464](https://github.com/opsmill/styrmin/issues/464)).
- **It does not change the URL scheme or the port** of the service.
- **It does not apply to the Gateway API**
  ([#465](https://github.com/opsmill/styrmin/issues/465)).

### What is not verified

- **Traffic through a controller of the override class.** No request is sent to
  the overridden host through such a controller, so nothing shows that it
  serves the host. What the end-to-end test does send goes through the
  environment's dedicated Traefik. Without an override, the host of the Prefect
  UI answers HTTP 200, before the override and after it is cleared. With the
  override class `tailscale`, the dedicated Traefik stops serving the default
  host, and the overridden host answers HTTP 404 through it, because the
  Ingress has another class.
- **Tailscale.** No Tailscale controller runs in the test fixtures. Whether the
  Tailscale operator needs a `spec.tls` section on an Ingress, and whether it
  ignores the host in the rules, is not known: the Tailscale documentation does
  not say. The first release writes no `spec.tls`. A test on a real operator
  settles it, and the override gets an optional field for the TLS hosts only
  if that test shows that it is needed.
- **The delay of a change.** The operator applies Ingress changes in its
  periodic pass, every 60 seconds by default. The measurement of an upgrade of
  a running Infrahub deployment is in
  [Migrate a driver whose external service renders its own Ingress](../drivers/migrating-external-service-ingress.md#what-was-measured-when-a-running-infrahub-deployment-moves-to-the-new-driver-version):
  with the default pass, the Prefect UI host answered HTTP 404 for about 12
  seconds in one run and about 7 seconds in another, and with a 5-second pass it
  did not stop answering in two runs. These are samples from one local vCluster,
  not limits. The delay of a change that an override makes was not measured
  separately.
- **Backup and restore.** The behavior of a backup and a restore of an
  environment whose deployments have Styrmin-built Ingresses is not known.

### Values that an override accepts

Styrmin checks both values when you write the override, before any task
starts. The cluster, the environment and the deployment have no such check on
their own `ingress_class` and `fqdn_suffix`; only the override does.

- **`ingress_class`** is a Kubernetes object name (a DNS-1123 subdomain):
  lowercase letters, digits, hyphens and dots, starting and ending with a
  letter or a digit, at most 253 characters. Styrmin writes it to
  `spec.ingressClassName` and to an annotation.
- **`fqdn_suffix`** is a DNS name: labels separated by dots, each of 1 to 63
  lowercase letters, digits or hyphens that starts and ends with a letter or a
  digit, at most 253 characters in total. It has no leading dot, no trailing
  dot, no doubled dot and no whitespace.
- An empty string is rejected for both. To clear a field, leave it out.
- An invalid value rejects the whole request, so Styrmin stores none of the
  overrides of that request.

### Set, view and clear an override

#### In the UI

To set or clear an override on an existing deployment:

1. Open the deployment, go to the **Settings** tab, and click **Update
   Settings**.
2. In the **Edit configuration** drawer, go to the **Services** section. Below
   the service name overrides, the group **Service ingress overrides** lists
   each external service with the fields **Ingress class** and **FQDN suffix**.
   An internal service has no fields.
3. Type the class, the suffix or both. An empty field shows the placeholder
   `inherited`: the resolved value applies. For an invalid value, the field
   shows the rule that it breaks.
4. Click **Review & apply** and confirm.

To clear the override of a service, click **Clear** next to its fields, or empty
both fields, and apply.

To set an override when you create a deployment, use the group **Service
ingress overrides** on the **Deploy** form. It lists the external services of
the selected driver version, with the same fields. The path from a value typed
in the deploy form to the Ingress was not tested end to end. Component tests
cover the form.

The **Networking** card on the **Settings** tab shows each external service
with its effective **Ingress class** and **Host**, and marks each value
**Overridden** or **Inherited**. An internal service is not listed, because
Styrmin builds no Ingress for it and it has no class or host of its own.

#### With a manifest

Write a list of rows under `spec.config.services`, as `components` is written:

```yaml
apiVersion: styrmin/v1
kind: Deployment
metadata:
  name: infrahub-lab
spec:
  driver: infrahub
  version: "1.7.3"
  environment: lab
  config:
    services:
      - name: task-manager
        ingress_class: tailscale
        fqdn_suffix: tailnet.example.ts.net
```

- Each row names the service as the driver declares it: the driver service
  name, not a service name override.
- `spec.config` replaces the whole stored config on every apply. A manifest
  with other `spec.config` keys and no `services` clears the stored overrides.
  A manifest with an empty or no `spec.config` keeps the stored config,
  overrides included. To clear the last override of a deployment whose
  manifest sets nothing else, write `services: []`.
- `apply` writes the config together with the version, so the checks in
  [Errors that name the service](#errors-that-name-the-service) apply to
  `apply` too. See
  [Manifest `spec.config` format](../reference/styrminctl.md#manifest-specconfig-format).

#### With the API, the Python SDK and `styrminctl`

The input is `ServiceConfigInput`, with the fields `name`, `ingressClass` and
`fqdnSuffix`. It is a list of rows, not a map, in the `services` field of
`DeploymentConfigInput`, which `deploy`, `updateDeployment` and
`updateDeploymentVersion` (in `input`) accept:

```graphql
mutation {
  updateDeployment(
    deploymentId: "<deployment-id>"
    input: {
      services: [
        {
          name: "task-manager"
          ingressClass: "tailscale"
          fqdnSuffix: "tailnet.example.ts.net"
        }
      ]
    }
  ) {
    id
  }
}
```

The input replaces the whole stored config, as `components` does: a service
that is not in the list has no override after the write, and an empty list
clears every override. A write that sets `services` and nothing else also
removes the other stored config keys, such as `components`, `env_vars` and
`ip_whitelist`, so resend every config field that you keep.

```python
from styrmin_sdk import StyrminClient
from styrmin_sdk.models import ServiceConfigInput, UpdateDeploymentInput

async with StyrminClient(server_address="https://styrmin.example") as client:
    await client.deployments.update(
        deployment_id,
        input=UpdateDeploymentInput(
            services=[
                ServiceConfigInput(
                    name="task-manager",
                    ingress_class="tailscale",
                    fqdn_suffix="tailnet.example.ts.net",
                )
            ],
        ),
    )
```

`styrminctl deployments update` and `deployments update-version --config` take
the same payload as JSON:

```shell
# Warning: this payload replaces the whole stored config. Add every other
# config field that you keep.
uv run styrminctl deployments update <deployment-id> \
  --config '{"services": [{"name": "task-manager",
                           "ingress_class": "tailscale",
                           "fqdn_suffix": "tailnet.example.ts.net"}]}'
```

To read an override back, query the deployment:

```graphql
query {
  deployment(deploymentId: "<deployment-id>") {
    serviceIngressOverrides {
      name
      ingressClass
      fqdnSuffix
    }
    deployedServices {
      driverServiceName
      scope
      ingressClass
      ingressClassOverridden
      humanReadableFqdn
      fqdnSuffixOverridden
    }
  }
}
```

- `serviceIngressOverrides` lists the stored overrides, sorted by service
  name. It is empty when there is none.
- On each `deployedServices` entry, `ingressClass` is the effective class of the
  Ingress that Styrmin builds. It is null for a service that is not external.
  `ingressClassOverridden` is `true` when it comes from the override.
  `humanReadableFqdn` and `humanReadableUrl` use the override suffix, and
  `fqdnSuffixOverridden` is `true` when they do. `primaryFqdn` does not change.
- The stored override is also in `Deployment.config` under `services`. The
  SDK's `deployments.get()` and `styrminctl deployments get` do not select the
  new `deployedServices` fields or `serviceIngressOverrides`. They return
  `config`, which includes `services`, and `humanReadableFqdn` with the
  override suffix.

### Errors that name the service

Each error below carries a code in `extensions.code` and names the service.

| Code | When | What to do |
|---|---|---|
| `UNKNOWN_SERVICE_INGRESS_OVERRIDE` | The request adds or changes an override on a service that the driver version of the deployment does not declare. The message lists the services that the version declares. | Use a service name from the list. |
| `SERVICE_INGRESS_NOT_BUILT` | The request adds or changes an override on a service that the driver version declares with `scope: internal`. The message says that Styrmin does not build its Ingress and the override has no effect. | Remove the override. An internal service cannot have one. |
| `SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED` | A driver version change would leave a stored override on a service that the target version removes or declares `internal`. Styrmin refuses the change before any pod changes and keeps the override. | Clear the override, then change the driver version: see below. |
| `DUPLICATE_SERVICE_NAME` | The `services` list has the same service name in two rows. | Keep one row for each service. |
| `VALIDATION_ERROR` | A class or a suffix breaks the rules in [Values that an override accepts](#values-that-an-override-accepts). | Fix the value. |

The checks run against the driver version that the deployment is bound to
after the write: the pinned version for `updateDeployment`, the target version
for `updateDeploymentVersion`.

Clearing an override is always accepted, even when the service no longer
exists in the driver version. A service of `kind` `tcp` or `udp` that is
`external` passes the check, because the check reads the scope only. Styrmin
builds no Ingress for it, so its override has no effect. This is read in the
code and was not run.

#### Change the driver version of a deployment that has an override

The message of `SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED` says: "Clear the
override of '`<service>`' in the same request, or keep a driver version that
declares it external." In the API, the SDK, `styrminctl` and a manifest, you
clear the override by sending the config without it, in the request that
changes the version. See [Set, view and clear an override](#set-view-and-clear-an-override).

The **Upgrade** dialog in the UI sends only the application version and the
driver version. It sends no `services`, so it cannot clear an override in the
same request. The dialog shows the server's message as it is. Do this instead:

1. On the **Settings** tab, click **Update Settings**. In the **Services**
   section, click **Clear** next to the fields of the service, and click
   **Review & apply**. Clearing is accepted on the current driver version.
2. Click **Upgrade** again. The deployment publishes the service with the
   resolved class and suffix.
3. If you still want an override, set it again after the upgrade, on a service
   that the new driver version declares external.

See also
[Change a deployment's driver version](../drivers/changing-driver-versions.md#stored-service-ingress-overrides).

### Rolling back Styrmin

The config model of a release before this feature rejects a config key that it
does not know. Such a release therefore rejects a stored config that has a
`services` block. This is read in the code, as it is for replica overrides, and
was not tested. Clear every service ingress override before you roll Styrmin
back.

### Limits

- **One class and one suffix for each service.** There is no list of hosts.
- **Deployment level only.** There is no default at the environment or
  cluster level.
- **External `http` and `https` services only.** Styrmin builds no Ingress for
  an internal service, and none for a `tcp` or `udp` service.

### Next steps

- [Ingress and networking](./ingress-and-networking.md): the Ingress that
  Styrmin builds, and how it chooses the hosts.
- [Migrate a driver whose external service renders its own Ingress](../drivers/migrating-external-service-ingress.md):
  the breaking change for drivers that declare `external`.
- [Change a deployment's driver version](../drivers/changing-driver-versions.md):
  the checks on a driver version change.
- [`styrminctl` reference](../reference/styrminctl.md#manifest-specconfig-format):
  the format of the manifest `spec.config`.
