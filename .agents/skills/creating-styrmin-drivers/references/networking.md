# Networking: what Styrmin allows, and the policy a driver ships

## What Styrmin writes in every deployment namespace

Each deployment runs in its own namespace, `styrmin-<deployment id>`. Styrmin 0.1.54 writes these
NetworkPolicies in it. On a cluster that enforces network policies (Cilium, Calico, kind's kindnet),
they decide which connections work:

| Policy | Effect |
|---|---|
| `default-deny-egress` | **No pod may open any connection**: not DNS, not its own database, not the internet. |
| `default-deny-ingress` | Pods accept connections only from pods of the same namespace. |
| `allow-traefik-ingress` | Pods accept connections from the environment's ingress controller. |
| `allow-egress-to-environment` | Pods may connect to the *other* namespaces of the environment (not their own). |
| `allow-environment-to-<component>` | Other deployments of the environment may reach a declared service's port. |
| `infrahub-netpolicy-egress`, `prefect-netpolicy-egress`, `traefik-netpolicy-egress` | Egress for Infrahub, Prefect and Traefik pods only (opsmill/styrmin#284). |

So a pod of your application can receive connections, but cannot open any until a policy allows
it. Kubernetes adds up the policies that select a pod: one extra policy that allows egress is enough.

Symptoms of a missing egress policy: init containers stuck in `Init:0/1`, logs with
`could not translate host name`, `Temporary failure in name resolution`, `connection timed out`
to the database, and the deployment failing with `Deployment did not reach Ready within 270s`.

## The policy to ship

Put this NetworkPolicy in the chart's extra-objects value. It selects every pod of the deployment
(`podSelector: {}`), including Helm hook Jobs such as database migrations.

```yaml
- apiVersion: networking.k8s.io/v1
  kind: NetworkPolicy
  metadata:
    name: styrmin-<app>-egress
  spec:
    podSelector: {}
    policyTypes: [Egress]
    egress:
      # DNS
      - to:
          - namespaceSelector: {}
            podSelector:
              matchExpressions:
                - key: k8s-app
                  operator: In
                  values: [kube-dns, coredns]
        ports:
          - port: 53
            protocol: UDP
          - port: 53
            protocol: TCP
      # The other pods of this deployment: application -> database, cache, queue
      - to:
          - podSelector: {}
      # Only when the application needs the internet (plugins, webhooks, git clones, update checks)
      - to:
          - ipBlock:
              cidr: 0.0.0.0/0
              except: [10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 100.64.0.0/10]
```

Leave out the internet rule when the application does not need it. Do not allow the private ranges:
they hold the cluster's own services, including Styrmin's server.

## Where to put it

Look in `helm show values` for one of these keys, in this order:

1. the main chart: `extraDeploy`, `extraObjects`, `extraManifests`, `extraResources`;
2. a subchart: every Bitnami chart (`postgresql`, `redis`, `valkey`, `mariadb`, `mongodb`,
   `rabbitmq`) has `extraDeploy`, set as `<subchart>.extraDeploy`;
3. the main chart's own `networkPolicy` values, when they can allow egress to DNS and to the
   namespace's pods.

The value is a list of objects (some charts take a list of strings rendered with `tpl`; read the
chart's template to see which). Check in the rendered manifests that the NetworkPolicy is there,
once: two charts rendering a policy with the same name fail the install.

Bitnami subcharts ship their own `networkPolicy` (enabled by default in recent versions), which
allows the database pod's egress. It does not cover your application's pods.

## When no value can carry the policy

Some charts have none of these keys (for example the Wiki.js chart). The pods of such a chart
cannot resolve DNS under Styrmin, and the driver cannot fix that through the chart. (A chart's own
`networkPolicy` that allows all egress, like Uptime Kuma's, is enough: enabling a policy only adds
allowed connections, so try it first and let `check_driver.py` say.)

- **One container** (the application and, at most, a database file on a volume): write the driver
  on the bjw-s app-template chart (`oci://ghcr.io/bjw-s-labs/helm/app-template`, version 5.2.1).
  Its values describe the Deployment, Service, Ingress, volume and NetworkPolicies directly. Copy
  [examples/app-template/](../examples/app-template/) and change the image, the port, the volume
  path and the environment variables. The scaffold does not draft this case.
- **Several workloads** (the application and its own database): do not rewrite the chart. Write
  in the README that the chart cannot run under Styrmin until opsmill/styrmin#284 allows DNS and
  same-namespace egress, and stop.

## Service names and URLs

- Applications of the same environment reach a declared service by its short name: Styrmin
  creates a Service named after `spec.services[].name` in every namespace of the environment.
  Inside its own deployment, the application reaches its database and cache by the chart's Service
  names (`styrmin-postgresql`, `styrmin-redis-master`, ...).
- An external service gets two hosts: `primary_fqdn`
  (`<driver name>-<deployment id>.<fqdn suffix>`) and `human_readable_fqdn`
  (`<service name>-<environment name>.<fqdn suffix>`). Put both on the chart's Ingress.
- Users open `{{ instance.config.external_url_scheme }}://<host>` plus
  `:{{ instance.config.external_url_port }}` when the port is not 80 or 443. Applications that need
  their own URL (allowed hosts, base URL, CSRF trusted origins) take it from these values.
- Service names must be unique in an environment: two deployments of drivers that declare the same
  service name cannot run in the same environment.
