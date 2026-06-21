# Contract: Deployment Manifest Schema (`apiVersion: styrmin/v1`, `kind: Deployment`)

This contract defines the YAML manifest format consumed by `styrminctl deployments apply`. It is the user-facing contract — changes to it are public-API changes.

## Top-level shape

```yaml
apiVersion: styrmin/v1
kind: Deployment
metadata:
  name: <string>          # optional in manifest; required at resolve-time
spec:
  driver: <string>        # required
  version: <string>       # optional in manifest; required at resolve-time
  environment: <string>   # optional in manifest; required at resolve-time
  cluster: <string>       # optional always; disambiguation hint only
  config: <object>        # optional; defaults to {}
  parameters: <object>    # optional; defaults to {}
```

## Field reference

| Path | Type | Required in manifest | Override sources | Notes |
|---|---|---|---|---|
| `apiVersion` | string literal `"styrmin/v1"` | yes | none | exact match |
| `kind` | string literal `"Deployment"` | yes | none | exact match; only `Deployment` supported in v1 |
| `metadata.name` | string | optional | `--name` / `STYRMIN_NAME` | not allowed with `--name` in batch mode |
| `metadata` (other keys) | n/a | — | — | extras forbidden |
| `spec.driver` | string | **yes** | none | not overridable; required to disambiguate the manifest's intent |
| `spec.version` | string | optional | `--version` / `STYRMIN_VERSION` | quoted for YAML clarity |
| `spec.environment` | string | optional | `--environment` / `STYRMIN_ENVIRONMENT` | resolved by name; `cluster` disambiguates |
| `spec.cluster` | string | optional | `--cluster` / `STYRMIN_CLUSTER` | only required when env name is ambiguous |
| `spec.config` | mapping | optional | none | full replacement on update; see [Config shape](#config-shape) |
| `spec.parameters` | mapping | optional | none | full replacement on update; a `{name: value}` map (the SDK flattens it to the backend's `[{name, value}]` list) |
| `spec` (other keys) | n/a | — | — | extras forbidden |

## Config shape

`spec.config` is validated against the same typed `DeploymentConfigInput` the
`deploy` (create) and `updateDeployment` mutations share, so a single manifest
applies identically whether `apply` creates or updates the deployment. Its
fields mirror the backend `DeploymentConfig` model. Two fields use a
**list-of-`{name, value}`** shape (not a map):

- `config.env_vars` — deployment-scoped environment variables.
- `config.components[].env_vars` — per-component environment variables.

```yaml
spec:
  driver: acme/my-driver
  config:
    env_vars:
      - name: MY_ENV
        value: value01
    components:
      - name: server
        env_vars:
          - name: LOG_LEVEL
            value: debug
```

> Prior to this unification the create path required `config.env_vars` as a
> `{name: value}` map while update required the list — the same manifest could
> apply on update but fail on create. Both now accept the list shape.

## Required vs optional in detail

A field is *required at resolve-time* if it must have a value before any backend call is made. The required-at-resolve-time fields are:

- `name` (from manifest, env, or flag)
- `driver` (manifest only)
- `version` (from manifest, env, or flag)
- `environment` (from manifest, env, or flag)

Failure to resolve any of these → `MissingRequiredFieldError` with a message that names the field and the three sources that can supply it.

## Validation rules

1. **Schema strictness**: `extra="forbid"` at every level. Unknown top-level keys, unknown `metadata.*`, and unknown `spec.*` all fail validation.
2. **`apiVersion` and `kind`**: literal-equal to the supported values (`"styrmin/v1"` and `"Deployment"`). Any other value fails with a message listing the supported values.
3. **`spec.driver`**: required, non-empty after stripping. Empty string fails.
4. **`spec.config` / `spec.parameters`**: must be objects (mappings) when present. Lists, scalars, or null fail validation.
5. **YAML parse errors**: surfaced unchanged to the user with the file path prepended.
6. **Empty document**: an empty YAML document or a document containing only `null` fails validation with `"manifest <path>: empty document"`.

## Multi-document files

A single YAML file may contain multiple manifests separated by `---`:

```yaml
apiVersion: styrmin/v1
kind: Deployment
metadata: {name: a}
spec: {driver: d1, version: "1.0.0", environment: prod}
---
apiVersion: styrmin/v1
kind: Deployment
metadata: {name: b}
spec: {driver: d2, version: "1.0.0", environment: prod}
```

Each document is validated and applied independently. A failure in one does not prevent processing the others.

## Examples

### Minimum manifest (with overrides supplying the rest)

```yaml
apiVersion: styrmin/v1
kind: Deployment
spec:
  driver: acme/my-driver
```

Required at apply-time: `--name`, `--version`, `--environment` (or env vars).

### Fully specified manifest

```yaml
apiVersion: styrmin/v1
kind: Deployment
metadata:
  name: my-app
spec:
  driver: acme/my-driver
  version: "1.2.3"
  environment: production
  cluster: us-east
  config:
    log_level: info
  parameters:
    replicas: 2
```

### Multi-document, mixed

```yaml
apiVersion: styrmin/v1
kind: Deployment
metadata: {name: frontend}
spec: {driver: acme/web, version: "2.0.0", environment: prod}
---
apiVersion: styrmin/v1
kind: Deployment
metadata: {name: backend}
spec: {driver: acme/api, version: "2.0.0", environment: prod}
```

## Versioning policy

`apiVersion: styrmin/v1` is fixed for v1. Any breaking change to the manifest schema (renamed/removed/typed fields) must increment to `styrmin/v2`. Adding new optional fields is non-breaking and stays in `v1`.
