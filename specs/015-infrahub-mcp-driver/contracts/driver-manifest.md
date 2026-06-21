# Contract: `infrahub-mcp` Driver Manifest (`driver.styrmin.yml`)

The contract a parsed `DriverSpec` MUST satisfy. Verified by extending
`backend/tests/unit/services/driver/test_deserializer.py`.

## Target manifest shape

```yaml
---
apiVersion: "styrmin.io/v1"
kind: ApplicationDriver
metadata:
  name: infrahub-mcp
spec:
  version: "1"
  supported_versions: ">=1.1,<2.0"
  info:
    description: >-
      Infrahub MCP server — exposes an existing Infrahub instance to AI agents
      and IDE clients over the Model Context Protocol (token-passthrough auth).
    authors: [opsmill]
    license: Apache-2.0
    links:
      - link: Homepage
        url: 'https://www.opsmill.com/'
      - link: Documentation
        url: 'https://docs.infrahub.app'
      - link: Github
        url: 'https://github.com/opsmill/infrahub'
  helm:
    main:
      location: oci://registry.opsmill.io/opsmill/chart/infrahub-mcp   # confirm at impl
      version: 0.1.0                                                    # confirm at impl
  parameters:
    - name: infrahub_address
      label: "Infrahub address"
      kind: string
      # no default => required
    - name: mcp_read_only
      label: "Read-only mode"
      kind: boolean
      default: false
    - name: mcp_log_level
      label: "Log level"
      kind: enum
      values: ["debug", "info", "warning", "error"]
      default: info
  components:
    server:
      identifier:
        label:
          app.kubernetes.io/name: infrahub-mcp   # confirm selector at impl
  services:
    - name: infrahub-mcp
      kind: http
      scope: internal
      port: 8001
      component: server
  # NO actions block
```

## Assertions (deserialize)

Given `DriverSpecDeserializer().deserialize(data=<parsed yaml>)` → `DriverSpec`:

1. `isinstance(result, DriverSpec)` and `result.metadata.name == "infrahub-mcp"`.
2. `result.spec.actions == []` (no actions; no `actions.py` required — FR-005).
3. Exactly **one** Component named `server` with label selector `app.kubernetes.io/name: infrahub-mcp`.
4. Exactly **one** Service: `name=infrahub-mcp`, `kind=http`, `scope=internal`, `port=8001`, `component=server` (FR-002).
5. Exactly **three** parameters:
   - `infrahub_address`: `kind=string`, `default is None` (⇒ required — FR-003).
   - `mcp_read_only`: `kind=boolean`, `default is False`.
   - `mcp_log_level`: `kind=enum`, `values == ["debug","info","warning","error"]`, `default == "info"`.
6. No parameter named `infrahub_token` / `api_token` / similar (FR-006).
7. Deserialization raises **no** error (SC-001: zero schema/validation errors).

## Assertions (parameter validation — `validate_parameter_values`)

| Input | Expected |
|-------|----------|
| `{}` (nothing) | `ServiceError` — missing required `infrahub_address` |
| `{"infrahub_address": "https://infrahub.example"}` | OK → resolves with `mcp_read_only=False`, `mcp_log_level="info"` (SC-003) |
| `{"infrahub_address": "...", "mcp_read_only": "yes"}` | `ServiceError` — type mismatch (boolean) |
| `{"infrahub_address": "...", "mcp_log_level": "trace"}` | `ServiceError` — out-of-enum |
| `{"infrahub_address": "...", "bogus": 1}` | `ServiceError` — unknown parameter |
