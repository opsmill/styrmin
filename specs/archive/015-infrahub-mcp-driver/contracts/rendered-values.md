# Contract: `infrahub-mcp` Rendered Helm Values (`values.j2.yml`)

The contract the Jinja2 template MUST satisfy when rendered against a Deployment
context. Verified by a unit render test (Jinja2 render → `yaml.safe_load`).

## Target template

```yaml
---
fullnameOverride: styrmin-infrahub-mcp
mcp:
  authMode: token-passthrough
  readOnly: {{ parameters.mcp_read_only | tojson }}
  logLevel: "{{ parameters.mcp_log_level }}"
infrahub:
  address: "{{ parameters.infrahub_address }}"
```

(Exact chart key paths — `mcp.*`, `infrahub.address` — are confirmed against the
published chart `values.yaml` at implementation; the keys above are the FR-004
targets.)

## Sample render context

```python
context = {
    "parameters": {
        "infrahub_address": "https://infrahub.example.com",
        "mcp_read_only": False,
        "mcp_log_level": "info",
    },
}
```

## Assertions

Given `rendered = yaml.safe_load(Template(values_j2).render(**context))`:

1. `rendered["fullnameOverride"] == "styrmin-infrahub-mcp"` (FR-004, SC-002, naming convention).
2. `rendered["mcp"]["authMode"] == "token-passthrough"` (FR-004 fixed; SC-002).
3. `rendered["mcp"]["readOnly"] is False` for the sample; `True` when `mcp_read_only=True` (User Story 2).
4. `rendered["mcp"]["logLevel"] == "info"` for the sample; matches any valid enum value supplied (User Story 3).
5. `rendered["infrahub"]["address"] == "https://infrahub.example.com"` (FR-004, SC-002).
6. The render output, recursively, contains **no key named `apiToken`** (nor `infrahub.apiToken`) and no Infrahub token value anywhere (FR-006, SC-004).
7. The rendered text is valid YAML (`yaml.safe_load` succeeds).

## Negative / boundary

- Rendering with `mcp_read_only=True` → `rendered["mcp"]["readOnly"] is True`.
- Rendering with `mcp_log_level="debug"` → `rendered["mcp"]["logLevel"] == "debug"`.
- No context path requires `infrahub_token`; the template references no token variable.
