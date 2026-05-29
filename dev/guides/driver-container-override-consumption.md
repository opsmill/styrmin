# Driver Container Override Consumption Guide

This guide is for **driver authors** wiring a component's container
`command` / `args` to be overridable per deployment
(014-component-container-overrides). It documents how an operator-set override
reaches your `values.j2.yml`, how to render it, and what the platform
deliberately does **not** do for you.

The override is a close sibling of the env-vars consumption surface
([`driver-env-var-consumption.md`](driver-env-var-consumption.md)). The one
behavioural divergence recorded in
[ADR-045](../adr/adr-045-container-override-no-layering-and-omit-marker.md) is
**no layering** (component-scope only). Like env vars, the filters return an
**always-present list** (`[]` when unset) and the chart guards consumption with
a `{{- with }}` block.

## What reaches your template

Your driver's `values.j2.yml` is rendered with a `GlobalContext` dumped via
`model_dump(exclude_none=True)`. The resolved override for a component lives at:

| Path | Shape | What it carries |
|---|---|---|
| `components[<name>].container_override.command` | `list[str] \| None` | The operator's entrypoint override for that component, or absent when unset. |
| `components[<name>].container_override.args` | `list[str] \| None` | The operator's args override, or absent when unset. |

Unlike env vars there is **no environment- or deployment-wide scope** — a
`command`/`args` override is set only on a single component of a single
deployment. The resolved value is the component block's value or "unset".

## The canonical accessor: `component_command` / `component_args`

Use the two Jinja filters; emit the keys **unconditionally** in
`values.j2.yml` and let the chart guard consumption:

```jinja
command: {{ components | component_command("server") | tojson }}
args: {{ components | component_args("server") | tojson }}
```

Each filter returns the resolved non-empty list when the operator has set an
override, or **`[]`** when it is unset (component absent from the context, no
override block, or that slot unset).

In the chart's pod template, guard each with `{{- with }}` so an empty list
falls through to the image/chart default:

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

## The empty-list-marker contract

| Filter | Returns when unset | Returns when set |
|---|---|---|
| `component_env_vars` | `[]` (chart appends harmlessly) | `[{name, value}, ...]` |
| `component_command` / `component_args` | **`[]`** | `["...", ...]` |

- **Always emit the key** and `tojson` the list — do NOT wrap the emission in
  an `if`/omit guard. The key must be **present** in the rendered values so
  that *clearing* an override propagates: the operator applies HelmRelease
  `spec.values` via JSON merge-patch (RFC 7386), where an **omitted** key is
  left unchanged, so a cleared override would otherwise silently persist on the
  running pod.
- The **chart** owns the safety guard: `{{- with .Values.command }}` skips an
  empty list, so `[]` never blanks the container entrypoint — the image
  `ENTRYPOINT`/`CMD` (or chart default) applies. Always consume these values
  through a `with` guard; never render them unconditionally.
- `command` and `args` are independent — one may be overridden while the other
  falls through to the chart/image default.

## Declaring overridability (doc-only, no enforcement)

You may advertise that a component is overridable in `driver.styrmin.yml`:

```yaml
spec:
  container_overrides:
    - component: server
      container: simple-app          # informational: which rendered container
      command: true                  # advertises command overridability
      args: true                     # advertises args overridability
      description: "Override the server entrypoint/args for debug or worker mode."
```

This block is **doc-only**: it surfaces through
`ApplicationDriverVersion.containerOverrides` for discovery, but the platform
**does not require** a declared component to actually wire the filters, and it
does not validate operator values against it. A driver that **declares but does
not wire** the filters stores the override and silently never applies it
(US6 Sc.3 — identical to the env-vars no-enforcement policy in ADR-013 §5).
Conversely, wiring the filters without the doc block also works — the doc block
is purely for operator discoverability.

## What the platform does NOT do

- It never injects `command`/`args` into a container your template did not
  wire (no post-render injection — same boundary as ADR-013).
- It does not template or expand override values — they pass through verbatim
  (FR-014).
- It does not layer the value across scopes — there is exactly one source (the
  component block).

Operators set/clear overrides through the standard `updateDeployment` mutation
(and at create time via the `deploy` mutation's `config` JSON); the malformed
or mis-targeted ones are rejected at the write boundary before any reconcile.
