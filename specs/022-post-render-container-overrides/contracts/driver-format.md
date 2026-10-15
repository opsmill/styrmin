# Contract: Driver Format Changes

**Feature**: [../spec.md](../spec.md) | Research D-004, D-006, D-009.

## `driver.styrmin.yml`

`spec.container_overrides` is removed. A file that still contains it fails to load: a `before` model validator on `Specification` raises a `removed_key` error that names the block and links the migration guide. Other unknown keys under `spec` keep the generic `extra_forbidden` error.

```yaml
# Before (rejected after this change)
spec:
  container_overrides:
    - component: server
      container: simple-app
      command: true
      args: true
      description: ...

# After: nothing. The component container is the only declaration needed.
spec:
  components:
    server:
      container: simple-app
```

A component accepts `command` and `args` overrides when it declares `components.<name>.container`.

## `values.j2.yml`

`component_command` and `component_args` stay registered but fail rendering with `RETIRED_TEMPLATE_FILTER` ([errors.md](errors.md)), whether or not an override is set and wherever the call sits (`{{ ... }}` or `{% if ... %}`).

```jinja
{# Before (fails to render after this change) #}
command: {{ components | component_command("server") | tojson }}
args: {{ components | component_args("server") | tojson }}

{# After: nothing. Do not set command or args from overrides; Styrmin patches the
   component container after the chart renders. #}
```

`components[<name>].container_override` stays in the rendering context as read-only data. A template that writes it into a chart value brings back the old problems (the chart's default is lost when no override is set) and is not supported.

## Example drivers

| Driver | `spec.version` | Changes |
|--------|----------------|---------|
| `simple-app` | 2 → 3 | Remove `command`/`args` lines and their comment from `values.j2.yml`; remove `container_overrides` block |
| `infrahub` | 3 → 4 | Remove the `{% if component_args %}` / `args: null` blocks for `server` and `task-worker`, and the `command`/`args` blocks for `task-manager`; remove `container_overrides` block |
| `infrahub-enterprise` | 2 → 3 | Same as `infrahub` |

After the change no driver in the repository contains `component_command`, `component_args` or `container_overrides` (SC-002). A repository-wide test asserts this.
