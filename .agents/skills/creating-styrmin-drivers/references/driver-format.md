# `driver.styrmin.yml` reference (Styrmin 0.1.54)

The loader validates the file with strict schemas: an unknown key in `metadata`, `spec`,
`spec.info`, `spec.helm`, `spec.helm.main`, a service, a parameter, an action or a backup block
fails the load. It validates a backup block even when `enabled` is false. Components accept extra
keys (`cpu`, `memory`).

```yaml
---
apiVersion: "styrmin.io/v1"          # exactly this
kind: ApplicationDriver              # exactly this
metadata:
  name: <string>                     # the driver name users pick; keep it stable
spec:
  version: "<string>"                # the driver's version. Highest parseable version wins when
                                     # several loaded versions match a deployment
  supported_versions: "<PEP 440 specifier>"   # e.g. ">=4.1,<4.5"
  default_version: "<version>"       # optional, must satisfy supported_versions
  info:                              # required, may be {}
    icon: <https URL>                # optional; invalid -> dropped with a warning
    description: <text>
    authors: [<string>]
    license: <string>
    links:                           # each entry has exactly `link` and `url`
      - link: Documentation
        url: https://...
  helm:
    main:
      location: <repo URL>/<chart>   # HTTP repo: https://charts.example.com/<chart>
                                     # OCI: oci://registry.example.com/path/<chart>
                                     # Styrmin splits on the last "/": repository + chart name
      version: "<chart version>"
  components:                        # optional, a mapping
    <component>:
      identifier:
        label:                       # required, string values; matches workload AND pod labels;
                                     # Styrmin selects the workloads by the FIRST label only
          <key>: "<value>"
      container: <container name>    # optional DNS-1123 label; receives user env vars, image,
                                     # command and args overrides
      replicas: <1..2147483647>      # optional driver default count
      singleton: <true|false>        # optional; true = always 1 pod; not with replicas > 1
      backup:                        # optional, keys: enabled, kind, volume, volumes,
        enabled: true                # database_name, credentials_secret
        kind: disk|postgres|mariadb|mongodb|neo4j|action
        volume: <pod volume name>    # disk: required (volume or volumes)
        database_name: <name>        # dump strategies
  parameters:                        # optional; shown when a user creates a deployment
    - name: <name>                   # read as {{ parameters.<name> }}
      label: <text>
      kind: string|integer|boolean|enum
      default: <value of that kind>  # give one: a parameter without default is required, and a
                                     # later driver version cannot retire it
      values: [<string>]             # enum only, and required for enum
  services:                          # optional; if present, not empty
    - name: <dns label>              # unique in the driver AND in the environment at deploy time
      kind: http|https|tcp|udp
      scope: internal|external       # external = gets a URL host
      port: <1..65535>               # the port the container listens on
      component: <declared component>
  actions:                           # optional; at most one per (hook, mode)
    - name: <string>
      hook: setup|upgrade
      mode: pre|core|post            # setup has pre and post only
      description: <string>          # required
      location: "actions.py::<function>"
      parameters: []                 # optional
  env_vars:                          # optional, documentation only (shown in the UI)
    - name: <POSIX name>
      description: <text>
      level: deployment|component   # component: list them in components: [...]
```

## Errors the loader returns

| Error | Cause |
|---|---|
| `Extra inputs are not permitted` | an unknown key in `spec`, a service, a parameter or an action |
| `Input should be a valid string` | an unquoted number: `version: 1`, `version: 7.0` |
| `Invalid version string` | `supported_versions` is not a PEP 440 specifier |
| `default_version ... does not satisfy supported_versions` | default outside the range |
| `... is not a valid Kubernetes container name` | `container` with capitals or `_` |
| `singleton: true cannot be combined with replicas` | both set, replicas > 1 |
| `Service '<s>' references undeclared component` | `services[].component` typo |
| `enum kind requires a non-empty 'values' list` | enum parameter without values |
| `spec.container_overrides was removed` | old driver format |
| `Failed to clone git repository` | wrong URL or branch, or a private repository without token |

## Deploy-time errors from the spec

| Error | Cause |
|---|---|
| `COMPONENT_CONTAINER_NOT_FOUND` | `container` is not in a workload the component selects |
| `COMPONENT_CONTAINER_NOT_DECLARED` | a user override on a component without `container` |
| version refused | the app version is outside `supported_versions` |
| duplicate service name | another deployment of the environment declares the same service name |
