---
title: Ingress and networking
sidebar_position: 5
description: How a deployment becomes reachable on a URL, and how environments are kept apart on the network.
---

## Ingress and networking

Each application that you deploy through Styrmin gets a URL that a
browser or another service can reach.

### Two layers of ingress

A Styrmin cluster has two layers of ingress:

1. **The ingress for Styrmin.** It serves the UI and the GraphQL API at
   an address such as `styrmin.example.com`. You install it once when you
   set up the cluster (see the
   [DigitalOcean guide](../installation/digitalocean.md) for an example),
   and it does not change per deployment.
2. **An ingress controller per environment.** A Styrmin environment can
   have its own ingress controller, which serves the applications
   deployed in that environment (see
   [Dedicated ingress controller or shared ingress class](#dedicated-ingress-controller-or-shared-ingress-class)).

The two layers are separate because Styrmin has one server with a fixed
URL, while there are many applications, they change often, and they must
be isolated from each other.

### Why an environment can have its own ingress controller

An **ingress controller** is the program that accepts incoming HTTP
traffic and routes it to the service that the request is for. Styrmin
uses [Traefik](https://traefik.io/) as the dedicated ingress controller
of an environment.

An environment gets its own Traefik instance only when
`dedicated_ingress` is set for it (see
[Dedicated ingress controller or shared ingress class](#dedicated-ingress-controller-or-shared-ingress-class)).
A dedicated ingress controller gives the environment:

- **Isolation.** Environments often have different IP allow lists,
  different TLS certificates, or different load balancers in front of
  them. With a dedicated Traefik instance, you configure each
  environment's ingress on its own.
- **Self-contained cloned environments.** When you clone an environment
  (see [Why Styrmin?](../introduction/why-styrmin.md)) and
  `dedicated_ingress` is set for the new environment, the new
  environment gets its own Traefik instance too. Applications in the
  clone connect to each other through the clone's network, not to
  production.
- **Separate failures.** A misconfiguration in one environment's ingress
  does not stop the ingress of another environment.

The dedicated ingress controller is itself a deployment that Styrmin
manages: Styrmin installs it with a built-in driver, and you do not
install or manage it. When `dedicated_ingress` is set for an environment
that has no controller yet, Styrmin installs the controller when:

- you deploy, update, or upgrade an application in the environment;
- you update the cluster or environment config, or restore an
  environment backup, and the environment has applications.

Styrmin removes the controller when no application uses it any more:

- after you delete the last application in the environment
- after `dedicated_ingress` is turned off for the environment and every
  application has been redeployed to the shared ingress class
  (see the next sections)

While the removal runs and `dedicated_ingress` is still set for the
environment, Styrmin rejects deploying, updating and upgrading
applications in the environment. Try again after the removal completes,
and Styrmin installs a new ingress controller.

### Dedicated ingress controller or shared ingress class

The `dedicated_ingress` setting determines whether an environment gets
its own ingress controller:

- When the environment sets `dedicated_ingress`, or the environment does
  not set it and the cluster does, the environment gets a dedicated
  ingress controller and its applications are served through it. Any
  `dedicated_ingress` object turns it on, including an empty one (`{}`).
- When neither the environment nor the cluster sets `dedicated_ingress`,
  the applications' Ingress resources use the resolved `ingress_class`:
  the deployment's value, else the environment's, else the cluster's
  (`traefik` by default). The shared ingress controller of the
  Kubernetes cluster for that class serves them.

An environment that does not set `dedicated_ingress` takes the
cluster's value, so an environment cannot turn off a dedicated ingress
that the cluster sets.

After the chart renders, Styrmin sets or removes the class of every
Kubernetes Ingress resource of an application, including the Ingresses
of subcharts, so the driver's values template does not need to set it.
Styrmin does not change other routing resources that a chart renders,
such as a Traefik IngressRoute or a Gateway API HTTPRoute.

The Ingress that Styrmin builds for an external service
([below](#the-ingress-that-styrmin-builds-for-an-external-service)) is not
part of the chart, so this step does not apply to it. It follows the same
rules for the class, with one addition: a
[service ingress override](./service-ingress-overrides.md) replaces them
for one service.

- With a dedicated ingress controller, Styrmin removes
  `spec.ingressClassName` and sets the `kubernetes.io/ingress.class`
  annotation to `traefik`, the controller implementation. The dedicated
  ingress controller serves an Ingress by this annotation. It does not
  read IngressClass resources, so it does not serve an Ingress that sets
  `spec.ingressClassName`, whatever the value. An `ingress_class` set on
  the cluster, the environment or the deployment does not change the
  Ingress in this case.
- Without one, Styrmin sets `spec.ingressClassName` and the
  `kubernetes.io/ingress.class` annotation to the resolved
  `ingress_class`, whatever class the chart sets.
- Without a dedicated ingress controller and with an empty resolved
  `ingress_class`, Styrmin does not change the class that the chart
  sets. The resolved value is empty only when the cluster was created
  with `ingress_class: null` and neither the environment nor the
  deployment sets a class, or when the most specific level that sets
  `ingress_class` (the deployment, else the environment, else the
  cluster) sets an empty string.

In the last case, an Ingress whose chart sets no class has no class.
Kubernetes gives it the default IngressClass of the cluster, when the
cluster has one. Otherwise, whether an ingress controller serves it
depends on that controller: some serve an Ingress without a class,
others ignore it. When no controller serves it, the deployment still
reaches `RUNNING` and Styrmin reports no error, but the application's
URL does not respond, and `kubectl get ingress -n
styrmin-<deployment-id>` shows no address for the Ingress. To fix it,
set `ingress_class` on the cluster, the environment or the deployment.
Styrmin sets that class on the Ingress the next time it deploys the
application.

The two sections below describe how Styrmin changes the ingress of an
environment when `dedicated_ingress` changes on the cluster or on the
environment.

### Changing the dedicated ingress on the cluster

When you update the cluster config (with `styrminctl clusters update`,
the SDK, the `updateCluster` GraphQL mutation or the cluster detail
page) and the update turns `dedicated_ingress` on, changes its values,
or turns it off, Styrmin changes the ingress of each environment that
takes the cluster's value. It orders the changes so that the
applications stay reachable. Environments that set their own
`dedicated_ingress` keep their own value. See
[`clusters update`](../reference/styrminctl.md#clusters-update--change-a-clusters-config)
for the rest of the update.

When the update turns `dedicated_ingress` on or changes its values:

1. Styrmin creates the environment's ingress controller, or redeploys it
   with the new values. In an environment without applications, Styrmin
   creates no controller; it creates one when you deploy the first
   application, as before.
2. The applications stay on their current ingress while the controller
   is not `RUNNING` with the new values.
3. When the controller reaches `RUNNING`, Styrmin redeploys the
   applications onto it.

When the update turns `dedicated_ingress` off:

1. Styrmin redeploys the applications to their resolved `ingress_class`
   immediately.
2. Styrmin removes the controller after every application has been
   redeployed without the dedicated ingress, no application is
   `PENDING`, `DEPLOYING`, `FAILED` or `RESTORING`, and the controller is
   not `PENDING` or `DEPLOYING`. A controller that is still being
   created when you turn the setting off is removed after its creation
   has finished, so no controller is left running without a record in
   Styrmin.

A `FAILED` application keeps the controller because FluxCD rolls a
failed upgrade back to the previous release, whose Ingress can still use
the controller. Styrmin removes the controller after the application is
`RUNNING` again or deleted.

When the controller has failed or is being removed:

- The controller is `FAILED` and the update does not change the
  environment's `dedicated_ingress`: Styrmin redeploys the applications
  for the other changed values and leaves the controller as it is.
- A new or redeployed controller ends `FAILED`: the applications that
  wait to move onto it stay on their current config, because Styrmin
  never moves an application onto a controller that is not `RUNNING`.
  Submit the config again: Styrmin redeploys the controller again, and
  moves the applications when it is `RUNNING`.
- The controller is being removed (`DELETING`): Styrmin does not create
  a second controller, and the applications that would move onto one
  stay on their current config. Submit the config again after the
  removal has finished; Styrmin then creates a new controller and moves
  them. If the controller stays `DELETING`, see
  [A controller that stays `DELETING`](#a-controller-that-stays-deleting).
- The update turns `dedicated_ingress` off while the controller is
  `FAILED`: Styrmin redeploys the applications to the shared ingress
  class, then removes the controller.

When an environment's controller reaches `RUNNING` for any reason, for
example after the first deploy creates it, Styrmin also redeploys the
applications of that environment that are not yet at the config they
resolve to.

### A controller that stays `DELETING`

With an agent of Styrmin v0.1.48 or earlier, a race condition in the operator can
stop the removal of a dedicated ingress controller
([#446](https://github.com/opsmill/styrmin/issues/446)). Changes to
`dedicated_ingress` remove controllers more often, so you are more
likely to see it after a cluster update.

You see these symptoms:

- The controller deployment stays `DELETING` in Styrmin for more than a
  few minutes.
- Its namespace, `styrmin-<controller-id>`, stays `Terminating`.
- Its `StyrminDeployment` custom resource, also named
  `styrmin-<controller-id>`, still has the `styrmin.io/kopf-finalizer`
  finalizer although the operator logged `Deletion is processed`.

An agent of a release later than v0.1.48 removes the finalizer itself.
To read the agent's version, and to remove the finalizer, follow
[A `StyrminDeployment` that keeps its finalizer](./operator-and-crds.md#a-styrmindeployment-that-keeps-its-finalizer),
with `styrmin-<controller-id>` as both the name and the namespace. That
section also covers an agent later than v0.1.48 that still shows these
symptoms.

Once the finalizer is gone, Kubernetes deletes the namespace, Styrmin
marks the controller as deleted, and you can submit the cluster config
again to move the applications that waited.

### Changing the dedicated ingress of an environment

When you update an environment (with the `updateEnvironment` GraphQL
mutation or the SDK) and the update turns the environment's own
`dedicated_ingress` on, changes its values, or turns it off, Styrmin
changes the environment's controller in the same order as a cluster
update. See
[Changing the dedicated ingress on the cluster](#changing-the-dedicated-ingress-on-the-cluster).

- When the update turns `dedicated_ingress` on or changes its values,
  Styrmin creates the controller or redeploys it with the new values.
  The applications stay on their current ingress until the controller
  is `RUNNING` with the new values, then Styrmin redeploys them onto it.
  In an environment without applications, Styrmin creates no controller
  until you deploy the first application.
- When the update turns `dedicated_ingress` off and the cluster sets
  `dedicated_ingress`, the environment takes the cluster's value.
  Styrmin redeploys the controller with the cluster's values when they
  differ, in the same order.
- When the update turns `dedicated_ingress` off and the cluster does not
  set it, Styrmin redeploys the applications to the shared ingress class
  immediately, and removes the controller after they have moved.

A failed controller, and a controller that is being removed, are handled
as in a cluster update. When you submit the environment config again,
Styrmin retries a controller that could not be started, and redeploys a
controller whose values differ from the environment's value, for example
after an environment update made with an earlier Styrmin release, which
changed only the applications.

When you restore an environment backup whose `dedicated_ingress`
differs from the environment's current value, Styrmin changes the
controller in the same way, with the backed-up value, and attributes a
controller that it creates to you. A deployment that receives a restore
of its own backup is not redeployed: the restore creates its namespace
again with the Ingress of the backup. When the backup turns `dedicated_ingress` off,
such a deployment keeps the controller until Styrmin redeploys it for
another reason, for example when you update the deployment. See
[Restoring an environment](./backups-and-restores.md#restoring-an-environment).

The **Configuration** tab of the environment page does not edit
`dedicated_ingress`. While the environment sets it, including an empty
`dedicated_ingress: {}` that turns the controller on with default
values, the tab blocks saving, because a save from the tab would turn
`dedicated_ingress` off.

### A deployment that sets its own `dedicated_ingress`

A deployment can set its own `dedicated_ingress` in its config. It keeps
that value when a cluster or environment update changes the
environment's `dedicated_ingress`, so the update does not move it onto
the environment's controller. The controller runs with the
environment's values; the deployment's own value does not change it.

When a cluster or environment update changes another value of such a
deployment's resolved config, for example its environment variables or
the FQDN suffix, Styrmin redeploys the deployment immediately, whatever the
state of the controller. The deployment does not wait for the
controller, so Styrmin does not redeploy a `FAILED` controller for it.

### The Ingress that Styrmin builds for an external service

Each application driver declares the **services** it exposes: name, kind,
port, and scope (internal or external). The scope decides who builds the
Ingress:

- For a service with `scope: external` and `kind` `http` or `https`,
  Styrmin builds one Ingress. The driver's chart must not render an Ingress
  for that service.
- For a service with `scope: internal`, Styrmin builds no Ingress. If the
  chart renders an Ingress for it, the chart keeps it.
- A service with `kind` `tcp` or `udp` gets no Ingress, because an Ingress
  cannot route it, even when it is `external`.

Before Styrmin built these Ingresses, no code read `scope`: a chart rendered
every Ingress, and Styrmin patched its class and annotations afterwards. A
driver that declares an external service and renders its own Ingress for it
now gets two Ingresses on the same host: see
[Migrate a driver whose external service renders its own Ingress](../drivers/migrating-external-service-ingress.md).

The Ingress has these properties:

- **Name and namespace.** It is named `styrmin-svc-<driver service name>`
  and lives in the namespace of the deployment. The name uses the service
  name that the driver declares, not the service name override and not the
  id that Styrmin stores for the service. Both of those change in cases
  where the Ingress must keep its identity: the id changes when you change
  the driver version or write a service name override. A driver version that
  renames a service therefore gets a new Ingress object, and the operator
  deletes the old one.
- **Labels.** It carries `app.kubernetes.io/managed-by`,
  `styrmin.io/utility-kind: ingress`, `styrmin.io/release-reference` and
  `styrmin.io/service-name`, which holds the driver service name. It also
  carries `styrmin/environment_id` and `styrmin/deployment_id`, the labels
  that Styrmin puts on every object that a chart renders. A dedicated ingress
  controller serves only the Ingresses that have `styrmin/environment_id` with
  the id of its environment, so an Ingress without it is not served by that
  controller, and its host answers HTTP 404. Styrmin sets both labels. A driver
  author does not set them.
- **Backend.** One rule for each host, with the path `/` and path type
  `Prefix`. The backend is the ClusterIP Service that Styrmin creates for
  the service, on the declared port.
- **No `spec.tls`.** Styrmin writes no `spec.tls` on an Ingress that it
  builds.
- **Class and annotations without an override.** The same as on a chart
  Ingress: the resolved class (see
  [Dedicated ingress controller or shared ingress class](#dedicated-ingress-controller-or-shared-ingress-class)),
  the Traefik entry points, the external-dns host name and the Cloudflare
  setting. When the deployment sets `ip_whitelist`, it also has the
  allow-list middleware reference. The external-dns endpoints type is set
  when the cluster, the environment or the deployment sets it.
- **Class and annotations with an override.** See
  [Service ingress overrides](./service-ingress-overrides.md).
- **Without a resolved FQDN suffix**, building the Ingress fails with an
  error, as the patch of a chart Ingress does. A service ingress override that
  sets its own suffix does not remove the need for the resolved suffix on the
  other services.

#### How Styrmin chooses the hosts of a service

Styrmin generates each host from the **fully qualified domain name (FQDN)
suffix** that you configured on the cluster, the environment or the
deployment. It sets each label to lowercase, replaces every character other
than a letter, a digit or a hyphen with a hyphen, and cuts a label to 63
characters.

The Ingress of a service has up to two hosts:

```text
<service name>-<environment name>.<fqdn suffix>
<driver name>-<deployment id>.<fqdn suffix>
```

- **The readable host** has the resolved name of the service, which is the
  service name override of the deployment when there is one, and the name of
  the environment. Every external service has one. For `task-manager` in the
  environment `lab` with the suffix `example.com`, it is
  `task-manager-lab.example.com`.
- **The application address** has the name of the application driver and the
  id of the deployment. It is the same for every service of the
  deployment, so Styrmin puts it on one Ingress only: the Ingress of the
  first service that the driver declares, and only when that service is
  `external`. For a deployment of `generic-app`, whose only service `app` is
  external, the Ingress has both hosts. For a deployment of `infrahub`,
  whose first service `infrahub` is internal, no Styrmin-built Ingress has
  the application address, and the Ingress that the chart renders for the
  `infrahub` service keeps it. If the first service has a service ingress
  override, its Ingress has the readable host only.

Styrmin generates the hosts from the configuration, so you do not register a
hostname for each deployment. Add one **wildcard DNS record**
(`*.styrmin.io`) that points to the environment's ingress, and each
deployment gets a URL.

#### When Styrmin creates the Ingress

The operator creates, updates and deletes these Ingresses in its periodic
pass, as it does for the network policies, services and secrets that Styrmin
builds. A deployment therefore has the Ingress soon after it is created, and
not at the same moment as the Helm release:

- In the end-to-end test setup, which runs the pass every 5 seconds, the
  operator log of one run shows the `task-manager` Ingress created about one
  second after the deployment was created.
- The default interval is 60 seconds, so the Ingress can appear up to one
  interval after the deployment is created. The delay with the default
  interval was not measured.

When a driver version or an override stops requiring an Ingress, the operator
deletes it in the same way. Deleting the deployment removes its namespace,
and with it the Ingress.

The end-to-end tests check Kubernetes objects: the Ingress, its hosts, its
class, its annotations and its backend. They send no request to a host, and
no Tailscale operator runs in them.

### Networking between applications

Applications in the same environment, such as Infrahub and a PostgreSQL
database deployed next to it, connect to each other by Kubernetes
service name, not by external hostname. The traffic stays inside the
cluster, so a cloned environment is self-contained: Infrahub in the clone
connects to the PostgreSQL in the clone, not to production.

The driver declares which services are internal and which are external.
Styrmin builds an Ingress for each external service, and builds none for an
internal service.

#### Which connections the network policies allow

Styrmin writes network policies into the namespace of each deployment. On a
cluster whose network plugin enforces network policies, such as Cilium,
they allow these connections:

- **Inside a deployment.** A pod accepts connections from the other pods of
  its namespace. Which pods may open them depends on the outbound rules:
  Styrmin writes outbound rules for Traefik, Prefect and Infrahub pods only
  ([opsmill/styrmin#284](https://github.com/opsmill/styrmin/issues/284)).
- **To a declared service, from the environment.** The other deployments of
  the environment connect to each service that the driver declares, on the
  service's port only. Styrmin writes one policy for each component that
  serves a declared service, named `allow-environment-to-<component>`. It
  admits the namespaces labelled with the environment's
  `styrmin/environment_id`.
- **From a deployment to the rest of its environment.** The pods of a
  deployment connect to the other namespaces of the environment
  (`allow-egress-to-environment`). The policies of those namespaces then
  decide which ports answer.

A component that serves no declared service, such as a database that only
its own application uses, is reachable from its own namespace only. The
applications of another environment cannot connect to the applications of
this one.

A chart can add network policies of its own. Styrmin does not change them,
and they can admit more than the rules above.

#### Service aliases

Each deployment runs in its own namespace, `styrmin-<deployment id>`. So
that an application can reach a service of another deployment of its
environment by the service's short name, Styrmin writes a **service
alias** into the namespace of every other deployment of the environment.
An alias is an `ExternalName` Service named after the service, which
points to the service in its owner's namespace. It has the labels
`styrmin.io/service-alias=true` and `styrmin.io/deployment-id=<owner id>`.

Styrmin writes the aliases each time it creates, updates or upgrades a
deployment. Deleting a deployment through Styrmin, from the UI,
`styrminctl` or the SDK, deletes its aliases in the other namespaces, so
the names of its services stop resolving in the other applications.

An [environment clone](./backups-and-restores.md#cloning-an-environment)
restores none of the source's aliases, because they point to the
namespaces of the source environment. At the end of each counterpart
deployment's restore, Styrmin writes the aliases between that counterpart
and the other deployments of the new environment. A deployment that was
not cloned gets no alias in the new environment, so the clone cannot
reach it by short service name.

These aliases are not deleted:

- the aliases of deployments deleted with a Styrmin release earlier than
  the one that fixed
  [opsmill/styrmin#503](https://github.com/opsmill/styrmin/issues/503);
- an alias that the deletion failed to delete; the operator logs the
  failure;
- the aliases of a deployment whose namespace was deleted directly, for
  example with `kubectl delete namespace`, because Styrmin cannot tell
  that deletion from the one that a restore makes;
- an alias that a change of another deployment wrote at the end of the
  deletion, after the operator listed the aliases for the last time and
  before Kubernetes removed the deployment's `StyrminDeployment`;
- the aliases of a `StyrminDeployment` annotated
  `styrmin.io/skip-teardown`. A restore into another deployment deletes
  such a copy of the source's `StyrminDeployment`, and the source keeps
  running, so its aliases are still in use.

An alias that stays after its deployment is deleted points into a
namespace that no longer exists, so its name does not resolve, as it
would not without the alias. The next deployment of the environment that
uses the same service name replaces it.

##### Finding and deleting aliases that stay

This command lists each alias that points into a namespace that does not
exist. Each line names the namespace that holds the alias, the alias, and
the missing namespace:

```bash
kubectl get services --all-namespaces -l styrmin.io/service-alias=true \
  -o jsonpath='{range .items[*]}{.metadata.namespace} {.metadata.name} {.spec.externalName}{"\n"}{end}' |
while read -r namespace name target; do
  owner=$(echo "$target" | cut -d. -f2)
  kubectl get namespace "$owner" > /dev/null 2>&1 || echo "$namespace $name $owner"
done
```

Before you delete an alias, check that no deployment has the id in the
missing namespace's name, `styrmin-<deployment id>`, for example with
`styrminctl deployments get <deployment id>`. A restore deletes a
deployment's namespace and creates it again, and the deployment's aliases
must stay in the meantime. Then delete the alias:

```bash
kubectl delete service --namespace <namespace> <alias>
```

#### Listing the services of an environment

In the Python SDK, `environments.get_services()` lists the services of
every deployment of an environment. It takes the environment's ID, or its
name with the ID or name of its cluster, as `environments.get()` does, and
raises `ResourceNotFoundError` when no environment matches.

Each service gives:

- `resolved_name`: the name by which the other deployments of the
  environment connect to the service, and the name of its aliases. It is
  the service name that the driver declares, or the service name override
  of the deployment.
- `driver_service_name`, `kind`, `scope`, `port` and `component`, as the
  driver declares them.
- `deployment_id`: the deployment that owns the service.

The list includes the services of internal deployments, such as the
ingress controller of a dedicated ingress. `deployments.list()` leaves
these deployments out unless you pass `include_internal=True`. The list
leaves out deleted deployments, because Styrmin removes their services
when the deletion ends, and its order is not fixed.

The list gives no URL or FQDN. `deployments.get()` returns them for one
deployment, in `deployed_services`.

### What you configure

- **Once per cluster:** an FQDN suffix and an ingress for the Styrmin
  server. Both are part of the install; see the
  [DigitalOcean guide](../installation/digitalocean.md) for an example on
  a cloud provider.
- **Once per environment:** the ingress settings of the environment, such
  as load balancer IDs and IP allow lists. Styrmin stores them on the
  environment and passes them to the environment's dedicated Traefik
  instance.
- **Per deployment:** nothing is required. Styrmin generates the hostnames.
  To publish one external service with another ingress class or another FQDN
  suffix, set a
  [service ingress override](./service-ingress-overrides.md).

### Next steps

- [**Service ingress overrides**](./service-ingress-overrides.md): publish
  one service with another ingress class or FQDN suffix.
- [**Backups and restores**](./backups-and-restores.md): backups and
  restores of an environment.
- [**The operator and `StyrminDeployment`**](./operator-and-crds.md): the
  component that creates the ingress objects in the cluster.
