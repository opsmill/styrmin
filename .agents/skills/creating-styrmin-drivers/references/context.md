# The template context

`values.j2.yml` is a Jinja2 template. Styrmin renders it with the deployment's context: every
top-level key below is a Jinja variable. Undefined names render as an **empty string without an
error**, so check names against this page. Extra filters: `to_fqdn_label` (makes a DNS label) and
`split`. The filters `component_env_vars`, `component_command` and `component_args` are retired and
fail the render.

## A real context

This is the context of a deployment of a driver named `generic-app` with one external service
`app`, in the environment `local`, on Styrmin 0.1.54 (template body and ids shortened):

```yaml
app:
  name: generic-app                 # the driver name (metadata.name)
  version: "1.11.0"                 # the application version the user deployed
  helm:
    chart: {name: app-template, version: 5.2.1}
    repository: {url: oci://ghcr.io/bjw-s-labs/helm}
cluster:
  config: {fqdn_suffix: apps.localhost, ingress_class: traefik, ...}   # prefer instance.config
environment:
  name: local
  config: {}
  capabilities: {backup: {velero: {storage_location: styrmin-bsl-a64d3fdd-...}}}
deployment:
  config: {components: {app: {env_vars: {WHOAMI_PORT_NUMBER: "8080"}}}}
instance:
  deployment_id: a95868f8-1620-48b3-83af-03d9767fc359
  namespace: styrmin-a95868f8-1620-48b3-83af-03d9767fc359
  release_reference: styrmin-a95868f8-1620-48b3-83af-03d9767fc359   # the Helm release name
  config:                           # merged cluster + environment + deployment config: read this
    fqdn_suffix: apps.localhost
    external_url_scheme: http
    external_url_port: 8090
    ingress_class: traefik
    runtime_class: default
    standard_storage: {storage_class: local-path}
    fast_storage: {storage_class: local-path}
    components: {app: {env_vars: {WHOAMI_PORT_NUMBER: "8080"}}}
labels:
  deployment_id: a95868f8-1620-48b3-83af-03d9767fc359
  environment_id: 2a647b98-c77a-4f0b-83a5-5fa3f020b9a6
parameters:                         # every declared parameter, with the user's value or the default
  image_repository: traefik/whoami
  image_tag: v1.11.0
services:                           # keyed by spec.services[].name
  app:
    host: app
    kind: http
    port: 8080
    url: http://app:8080
    primary_fqdn: generic-app-a95868f8-1620-48b3-83af-03d9767fc359.apps.localhost
    human_readable_fqdn: app-local.apps.localhost
deployed_services:                  # services that exist in the environment, with their owner
  - {component: app, deployment_id: a95868f8-..., kind: http, port: 8080, resolved_name: app}
components:                         # absent when the driver declares no components
  app:
    name: app
    enabled: true
    config: {container: app, identifier: {label: {styrmin/component: app}}, backup: {...}}
    env_vars: {config: {WHOAMI_PORT_NUMBER: "8080"}}
utilities: [{kind: ingress}, {kind: service-discovery}]
```

Keys that only exist when set: `instance.config.env_vars`, `components.<name>.env_vars`,
`components.<name>.image_override`, `components.<name>.replica_override`,
`instance.config.dedicated_ingress`, `instance.config.ip_whitelist`. Guard them:
`{% if instance.config.ip_whitelist %}` or `(instance.config.env_vars or {})`.

## Patterns

```yaml
fullnameOverride: styrmin-myapp
image:
  tag: "v{{ app.version }}"                                   # the registry's tag format
ingress:
  enabled: true
  hosts:
    - host: "{{ services['myapp'].primary_fqdn }}"
    - host: "{{ services['myapp'].human_readable_fqdn }}"
persistence:
  storageClass: "{{ instance.config.standard_storage.storage_class }}"
  size: "{{ parameters.storage_size }}Gi"
```

The URL users open, for settings such as allowed hosts or a base URL:

```jinja
{%- set scheme = instance.config.external_url_scheme or "https" %}
{%- set port = instance.config.external_url_port %}
{%- set suffix = (":" ~ port) if port and port not in [80, 443] else "" %}
{%- set url = scheme ~ "://" ~ services['myapp'].primary_fqdn ~ suffix %}
siteUrl: "{{ url }}"
```

`{{ labels.environment_id }}` and `{{ instance.namespace }}` serve network policies that name the
environment or the namespace.

## Rules

- Read cluster and environment settings from `instance.config`, not `cluster.config`.
- Do not read env vars, image overrides, replica overrides or command overrides to pass them to the
  chart: Styrmin applies them after rendering.
- The context does not change during the life of an instance; do not read live cluster state.
