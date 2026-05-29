# Contract: Jinja Template Filters (driver consumption)

**File**: `backend/styrmin_backend/agent/service/kubernetes/resources/builders/application.py`

Two new filters, registered in `get_jinja_environment` alongside `component_env_vars`. These are how a driver author **consumes** a resolved override in `values.j2.yml` (FR-009, ADR-013 driver-side consumption boundary).

> **Design correction (implementation).** This contract originally prescribed
> an *omit-marker* (filter returns `None`; template guards with `{%- if _x is
> not none %}` and omits the key). Implementation E2E proved that breaks
> **clearing**: the operator applies HelmRelease `spec.values` via JSON
> merge-patch (RFC 7386), where an omitted key is left unchanged — so a cleared
> override never left the running pod. The shipped contract is the **empty-list
> marker** below (filter returns `[]`; template emits unconditionally; the
> chart guards with `{{- with }}`). See
> [ADR-045](../../../dev/adr/adr-045-container-override-no-layering-and-omit-marker.md).

## Signatures

```python
def component_command(components: object, name: str) -> list[str]:
    """Resolved `command` override for component `name`, or [] when unset.

    Returns [] when: `components` is not a dict, the component is absent
    from the rendering context, it has no resolved container_override block,
    or its `command` slot is unset. Returns the non-empty list when set."""

def component_args(components: object, name: str) -> list[str]:
    """Resolved `args` override for component `name`, or [] when unset.
    Same []-cases as component_command for the `args` slot."""
```

Registration:

```python
env.filters["component_command"] = component_command
env.filters["component_args"] = component_args
```

## Contract (matches the `component_env_vars` always-present-list convention)

| Filter | Returns when unset | Returns when set | Rationale |
|--------|--------------------|------------------|-----------|
| `component_env_vars` (existing) | `[]` | `[{name,value},...]` | `[]` + chart-append is harmless |
| `component_command` / `component_args` (new) | **`[]`** | `["...", ...]` | always-present key so *clearing* propagates under the operator's JSON merge-patch apply; the chart's `{{- with }}` guard skips `[]`, so the chart/image default flows through (FR-007/US2 Sc.2, FR-009) |

The platform never injects `command`/`args` into a container the driver template did not wire. An unwired driver stores-but-never-applies the override (FR-009, US6 Sc.3 — silent no-op, identical to ADR-013 env-var consumption).

## Reading from the rendering context

`render_value_template` renders against `GlobalContext.model_dump(exclude_none=True)`. The resolved override lives at `components[<name>].container_override.{command,args}` (from `ResolvedComponentContainerOverride`). Because `exclude_none=True` drops unset keys, the filters defensively guard every access and return `[]` on any miss — driver templates need no `is defined` checks.

## Canonical driver-author pattern (emit unconditionally; the chart guards with `with`)

In `values.j2.yml` — always emit the key:

```jinja
command: {{ components | component_command("server") | tojson }}
args: {{ components | component_args("server") | tojson }}
```

In the chart's pod template — guard with `{{- with }}` so an empty list falls through:

```yaml
{{- with .Values.command }}
command:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.args }}
args:
  {{- toYaml . | nindent 2 }}
{{- end }}
```

- Emit the key **unconditionally** (no `if`/omit guard): the key must be present so a cleared override overwrites the prior value under merge-patch.
- The chart's `{{- with }}` guard makes `[]` safe — it skips the key entirely, so the Helm chart's own `command`/`args` (or the image's `ENTRYPOINT`/`CMD`) apply.
- `command` and `args` are independent (FR-007/US2): one may be overridden while the other falls through.

## Unit tests (mandatory)

`backend/tests/unit/agent/test_render_value_template_container_overrides.py` (mirrors `test_render_value_template_env_vars.py`):

- Both set → both rendered.
- `command` set, `args` unset → `command:` emitted, `args:` key **absent** (chart default flows through).
- Neither set → neither key emitted, no `UndefinedError`.
- Empty-string element (`["sh","-c",""]`) → rendered verbatim.
- Filter returns `None` (not `[]`) for absent component / missing block.
