# Driver Env Var Consumption Guide

This guide is for **driver authors** writing or maintaining a `values.j2.yml`
template. It documents how operator-set environment variables reach the
template, how to render them through your chart, and what the platform
deliberately does **not** do for you.

For the operator-facing reference (where env vars get set, validated, and
queried), see [`dev/knowledge/backend/deployment-env-vars.md`](../knowledge/backend/deployment-env-vars.md).
The canonical contract for this consumption surface lives in
[`specs/010-driver-env-var-consumption/spec.md`](../../specs/010-driver-env-var-consumption/spec.md).

## What env vars reach your template

Your driver's `values.j2.yml` is rendered with a `GlobalContext` that the
platform dumps via `model_dump(exclude_none=True)`. Two fields carry resolved
env vars:

| Field | Shape | What it carries |
|---|---|---|
| `instance.config.env_vars` | `dict[str, str]` | The **deployment-effective** merged env vars (environment scope merged into deployment scope, deepest-wins). |
| `components[<name>].env_vars.config` | `dict[str, str]` | The **per-component** merged env vars (environment → deployment → component, deepest-wins). |

Both keys may be **absent** from the rendered context dict when no env vars
are set anywhere — `exclude_none=True` drops them. Always use defensive
accessors:

```jinja
{# deployment-effective dict #}
{{ instance.config.env_vars or {} }}

{# per-component dict — guard both the component and the env_vars sub-block #}
{%- set comp_env = (components.worker.env_vars.config
                    if (components.worker is defined and components.worker.env_vars)
                    else {}) %}
```

The platform resolves the merge order; you do not implement it. Operators
control which scope wins through the standard `updateEnvironment` /
`updateDeployment` mutations. Your template just consumes the merged result.

## How to render them

All three examples below use Jinja's `tojson` filter on names and values.
**Use it.** Operator-supplied values may contain newlines, quotes, leading
dashes, or other YAML-significant characters; without escaping, an unlucky
value will silently produce broken `values.yaml`. The platform does NOT
escape values for you — it is your template's responsibility.

### Single-component driver (the simple-app pattern)

The canonical shape: expose operator-set env vars through a chart-side
`extraEnv` value. Naming the value `extraEnv` (not `env`) makes it
**structurally additive** — chart-default env entries stay intact, operator
entries concatenate.

```jinja
# values.j2.yml
image:
  repository: my-app
  tag: "{{ app.version }}"

extraEnv:
{%- for name, value in (instance.config.env_vars or {}).items() %}
  - name: {{ name | tojson }}
    value: {{ value | tojson }}
{%- else %}
  []
{%- endfor %}
```

Corresponding chart-side hook in `templates/deployment.yaml`:

```yaml
env:
  - name: APP_DEFAULT_VAR
    value: "default-value"
  {{- with .Values.extraEnv }}
  {{- toYaml . | nindent 4 }}
  {{- end }}
```

The chart's defaults render first, the operator entries append after. If two
entries collide on `name`, Kubernetes uses **whichever appears last** in the
list — pick your ordering accordingly.

### Multi-component driver (per-component scoping)

When your driver declares multiple components, render each component's
slice from `components[<name>].env_vars.config`. Each component receives its
own env→dep→comp-merged dict; peer components are not affected.

```jinja
# values.j2.yml — multi-component driver with `api` and `worker`
api:
  extraEnv:
{%- set api_env = (components.api.env_vars.config
                   if (components.api is defined and components.api.env_vars)
                   else {}) %}
{%- for name, value in api_env.items() %}
    - name: {{ name | tojson }}
      value: {{ value | tojson }}
{%- else %}
    []
{%- endfor %}

worker:
  extraEnv:
{%- set worker_env = (components.worker.env_vars.config
                      if (components.worker is defined and components.worker.env_vars)
                      else {}) %}
{%- for name, value in worker_env.items() %}
    - name: {{ name | tojson }}
      value: {{ value | tojson }}
{%- else %}
    []
{%- endfor %}
```

An operator setting `componentEnvVars: [{ component: "worker", envVars: { WORKER_QUEUE: "orders" } }]`
sees `WORKER_QUEUE=orders` only on the worker pods; the `api` pods are
unaffected.

### Combining chart-default env entries with operator-set ones

Two ordering choices, both legitimate. Pick the one that matches your app's
operational story.

**Chart-defaults first, operator entries override on collision** (typical):

```yaml
# templates/deployment.yaml
env:
  - name: LOG_LEVEL
    value: "warn"
  - name: APP_REGION
    value: "us-east-1"
  {{- with .Values.extraEnv }}
  {{- toYaml . | nindent 4 }}
  {{- end }}
```

If the operator sets `LOG_LEVEL=debug`, the appended entry comes after — and
because Kubernetes uses the **last** entry on duplicate `name`, `debug` wins.

**Operator entries first, chart-defaults override on collision** (rare; for
guard-rail scenarios where the chart enforces a value):

```yaml
# templates/deployment.yaml
env:
  {{- with .Values.extraEnv }}
  {{- toYaml . | nindent 4 }}
  {{- end }}
  - name: APP_REGION
    value: "us-east-1"
```

Same operator setting `LOG_LEVEL=debug` reaches the pod (no collision with
`APP_REGION`). But if the operator tries to set `APP_REGION=eu-west-2`, the
chart's default appears last and wins — the operator override is silently
discarded.

The platform imposes **no** precedence policy on chart-vs-operator
collisions. You choose.

## What the platform doesn't do

These are **not** bugs — they are deliberate non-features:

- **No enforcement that operator-set env vars are consumed.** A driver
  template that ignores `instance.config.env_vars` silently opts out. The
  values are stored, queryable, and editable, but never reach a pod.
- **No validation that `spec.env_vars` matches what the template
  consumes.** The driver-side declaration is informational only — it
  documents what your app respects, not what your template actually wires
  up.
- **No automatic chart-default merging.** The platform never inspects your
  chart's defaults. Concatenation, deduplication, and precedence on
  collisions are entirely your template's call.
- **No type coercion on values.** Operators submit strings; your chart
  receives strings. If your app needs a number or a boolean, your chart or
  app handles that conversion.
- **No migration for drivers from before 010.** Drivers that previously
  relied on the platform's post-render injection (008's `EnvVarsPatch`,
  removed in 010) silently opt out until their author updates the template.
  Until then, operator-set env vars are stored, queryable, and editable —
  but don't reach pods. This is a feature: each driver decides whether to
  expose the surface.

## Related

- Operator-facing reference: [`dev/knowledge/backend/deployment-env-vars.md`](../knowledge/backend/deployment-env-vars.md).
- Canonical contract: [`specs/010-driver-env-var-consumption/spec.md`](../../specs/010-driver-env-var-consumption/spec.md).
- Architecture record: [`dev/adr/adr-021-driver-env-var-consumption.md`](../adr/adr-021-driver-env-var-consumption.md).
- 008's original ADR (superseded for the injection portion): [`dev/adr/adr-019-deployment-env-vars.md`](../adr/adr-019-deployment-env-vars.md).
- Reference driver: `driver/examples/simple-app/values.j2.yml` and `driver/examples/simple-app/src/helm/templates/deployment.yaml`.
