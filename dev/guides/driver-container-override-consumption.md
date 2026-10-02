# Driver Container Override Consumption Guide

This guide is for **driver authors** wiring a component's container
`command` / `args` to be overridable per deployment
(014-component-container-overrides). It documents how a user-set override
reaches your `values.j2.yml`, how to render it, and what the platform
deliberately does **not** do for you.

Unlike env vars, `command`/`args` still flow through the values template. Env
vars moved to post-render injection into the declared component container in
017 ([ADR-055](../adr/0055-post-render-component-overrides.md),
[`driver-env-var-consumption.md`](driver-env-var-consumption.md)); moving
`command`/`args` onto the same mechanism is a follow-up. The override filters
return an **always-present list** (`[]` when unset), the chart guards
consumption with a `{{- with }}` block, and there is **no layering**
(component-scope only, [ADR-045](../adr/0045-container-override-no-layering-and-omit-marker.md)).

## What reaches your template

Your driver's `values.j2.yml` is rendered with a `GlobalContext` dumped via
`model_dump(exclude_none=True)`. The resolved override for a component lives at:

| Path | Shape | What it carries |
|---|---|---|
| `components[<name>].container_override.command` | `list[str] \| None` | The user's entrypoint override for that component, or absent when unset. |
| `components[<name>].container_override.args` | `list[str] \| None` | The user's args override, or absent when unset. |

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

Each filter returns the resolved non-empty list when the user has set an
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
| `component_command` / `component_args` | **`[]`** | `["...", ...]` |

- **Always emit the key** and `tojson` the list — do NOT wrap the emission in
  an `if`/omit guard. This was required while the operator merge-patched the
  HelmRelease (an omitted key was left unchanged, so a cleared override
  persisted). Since 017 the operator replaces the HelmRelease `spec` on update
  ([ADR-055](../adr/0055-post-render-component-overrides.md) §6), so an omitted
  key no longer lingers, but the always-present key stays the documented
  pattern and keeps the rendered values explicit.
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

This works because the operator strips `null`s before it applies the
HelmRelease, so the key is absent and the chart's own default flows through —
clearing reverts to the default (see
[ADR-045](../adr/0045-container-override-no-layering-and-omit-marker.md) §5 and
[ADR-055](../adr/0055-post-render-component-overrides.md) §6):

- on the **create POST**, `prune_none_on_create` strips them, so a first
  reconcile never persists a literal null that the unguarded chart would render
  and blank;
- on an **update**, the `spec` replace (JSON Patch `add /spec`) prunes them the
  same way.

The alternative is a **default fallback** — always emit the key, falling back to
the chart's documented default instead of `[]`:

```jinja
args: {{ ((components | component_args("server")) or ["gunicorn", "--config", "…"]) | tojson }}
```

Both clear correctly; pick based on the remaining trade-off:

| Approach | Pros | Cons |
|---|---|---|
| **`null` marker** (Infrahub) | No duplicated default; clearing reverts to the chart default | Relies on the operator's `null` prune on create and update (ADR-045 §5, ADR-055 §6) |
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
does not validate user values against it. A driver that **declares but does
not wire** the filters stores the override and silently never applies it
(US6 Sc.3 — the no-enforcement policy ADR-013 §5 used to apply to env vars).
Conversely, wiring the filters without the doc block also works — the doc block
is purely for user discoverability. Its `container` field is informational and
separate from `components.<name>.container`, the component container env vars
are injected into; the two are not cross-validated.

## What the platform does NOT do

- It never injects `command`/`args` into a container your template did not
  wire (no post-render injection for these two slots yet; env vars moved to
  post-render in ADR-055).
- It does not template or expand override values — they pass through verbatim
  (FR-014).
- It does not layer the value across scopes — there is exactly one source (the
  component block).

Users set/clear overrides through the standard `updateDeployment` mutation
(and at create time via the `deploy` mutation's `config` JSON); the malformed
or mis-targeted ones are rejected at the write boundary before any reconcile.
