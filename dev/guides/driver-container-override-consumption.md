# Driver Container Override Consumption Guide

This guide is for **driver authors** wiring a component's container
`command` / `args` to be overridable per deployment
(014-component-container-overrides). It documents how an operator-set override
reaches your `values.j2.yml`, how to render it, and what the platform
deliberately does **not** do for you.

The override is a close sibling of the env-vars consumption surface
([`driver-env-var-consumption.md`](driver-env-var-consumption.md)). The one
behavioural divergence recorded in
[ADR-045](../adr/0045-container-override-no-layering-and-omit-marker.md) is
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

## When the chart consumes the value *unconditionally* (no `with` guard)

The empty-list-marker contract above assumes the chart guards consumption with
`{{- with .Values.command }}`, so an empty list is skipped. **Some upstream
charts you don't control consume the value unconditionally** — e.g. the Infrahub
chart renders `args: {{- toYaml .Values.infrahubServer.infrahubServer.args }}`
with no `with` guard and exposes no `command` field at all. Handing such a chart
the `[]` marker would **replace** its default args with an empty list and blank
the entrypoint.

For these charts you have two Jinja-side options. The Infrahub examples
(`driver/examples/infrahub`, `driver/examples/infrahub-enterprise`) use the
**`null` clear-marker** — render the override when set, or a literal `null` when
unset, with no need to re-declare the chart's default:

```jinja
{%- if components | component_args("server") %}
args: {{ components | component_args("server") | tojson }}
{%- else %}
args: null
{%- endif %}
```

This works because the two HelmRelease apply paths treat the `null` exactly as
clearing needs (see [ADR-045](../adr/0045-container-override-no-layering-and-omit-marker.md) §5):

- on a **merge-patch update**, `null` *deletes* the key (RFC 7386) so the
  chart's own default flows through — clearing reverts to the default;
- on the **create POST**, the operator strips `null`s first
  (`prune_none_on_create`), so a first reconcile treats it as absent rather than
  persisting a literal null that the unguarded chart would render and blank.

The alternative is a **default fallback** — always emit the key, falling back to
the chart's documented default instead of `[]`:

```jinja
args: {{ ((components | component_args("server")) or ["gunicorn", "--config", "…"]) | tojson }}
```

Both clear correctly; pick based on the remaining trade-off:

| Approach | Pros | Cons |
|---|---|---|
| **`null` marker** (Infrahub) | No duplicated default; clearing reverts to the chart default | Relies on the operator's create-path `null` prune (ADR-045 §5) |
| **Default fallback** | Self-contained in the template | Duplicates the chart's default, which can drift on a chart-version bump (pin the chart and keep it in sync) |

Either way, **only the fields the chart actually exposes are overridable.** The
Infrahub chart wires `args` but not `command`, so its examples advertise
`args: true` only and leave `command` off the doc block — declaring
`command: true` would be a misleading silent no-op.

The canonical `{{- with }}` chart pattern (always-present empty-list marker, see
`driver/examples/simple-app`) remains preferred whenever you **own** the chart,
because it gets clearing right *and* avoids duplicating the default. The two
options above are escape hatches for charts you don't control.

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
