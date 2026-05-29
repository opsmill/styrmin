# Quickstart: Component-Scope `command` / `args` Overrides

Two audiences: the **driver author** (one-time, wires a component to be overridable) and the **deployment operator** (sets/clears overrides per deployment, no driver fork). SC-002 target: a driver author makes a component overridable end-to-end in ≤10 changed lines.

---

## Part A — Driver author: make a component overridable (one-time)

### A1. Declare it (doc-only) in `driver.styrmin.yml`

```yaml
spec:
  components:
    server:
      identifier:
        label:
          app.kubernetes.io/name: simple-app

  # NEW: doc-only declaration — informational, discoverable via the API/UI.
  container_overrides:
    - component: server
      container: simple-app          # which rendered container the override targets
      command: true                  # advertises command overridability
      args: true                     # advertises args overridability
      description: "Override the server entrypoint/args for debug or worker mode."
```

The declaration does **not** enforce consumption — the platform never requires a declared component to actually wire the filters (FR-010).

### A2. Consume it in `values.j2.yml` (the part that makes it real)

```jinja
{%- set _cmd = components | component_command("server") %}
{%- if _cmd is not none %}
command: {{ _cmd | tojson }}
{%- endif %}
{%- set _args = components | component_args("server") %}
{%- if _args is not none %}
args: {{ _args | tojson }}
{%- endif %}
```

The `if … is not none` guard is required: when the operator has not set an override, the filter returns `None`, the key is omitted, and the chart/image default applies (FR-007/US2 Sc.2). A driver that declares but does **not** wire these filters stores the override and silently never applies it (US6 Sc.3).

Materialise the driver version and confirm the declaration surfaces:

```graphql
query { applicationDriverVersion(id: "…") { containerOverrides { component command args container } } }
```

---

## Part B — Operator: set, change, and clear overrides

No driver source change required for any of the below.

### B1. Override `args` on one component (US1) — SDK

```python
from styrmin_sdk.models import UpdateDeploymentInput, ComponentConfigInput

await client.deployments.update(
    deployment_id,
    input=UpdateDeploymentInput(
        components=[ComponentConfigInput(name="server", args=["--log-level=debug"])],
    ),
)
```

Confirm the redeploy; on the next reconcile the `server` pod's container reports `args == ["--log-level=debug"]`.

### B2. Override `command` independently of `args` (US2)

```python
await client.deployments.update(
    deployment_id,
    input=UpdateDeploymentInput(
        components=[ComponentConfigInput(
            name="server",
            command=["python", "-m", "foo.cli", "worker"],
            args=["--log-level=debug"],   # carry the previously-set args; both are independent slots
        )],
    ),
)
```

Setting `command` while leaving `args` unset (omit it) lets `args` fall through to the chart default — the two fields never disturb each other.

### B3. Clear an override → fall back to chart default (US3)

Clearing is **null/omit**, never `[]`. Under full-replacement semantics, submit the component block without the field you want cleared:

```python
await client.deployments.update(
    deployment_id,
    input=UpdateDeploymentInput(
        components=[ComponentConfigInput(name="server", command=["python","-m","foo.cli","worker"])],
        # `args` omitted → cleared; the chart's default args reach the pod. `command` stays overridden.
    ),
)
```

After clearing, the field is absent from subsequent reads (`componentContainerOverrides`).

### B4. CLI (rides the typed `--config` JSON)

```bash
styrminctl deployments update <deployment-id> --config '{
  "components": [
    {"name": "server", "command": ["python","-m","foo.cli","worker"], "args": ["--log-level=debug"]}
  ]
}'
```

### B5. Frontend

Deployment detail → Configuration → the per-component override section: expand `server`, edit the **Command** and **Args** lists, Apply, and confirm the redeploy in the diff/impact dialog.

### B6. Read overrides back (incl. orphans)

```graphql
query {
  deployment(id: "…") {
    componentContainerOverrides { component command args isOrphaned }
  }
}
```

---

## Part C — Safety & lifecycle (verify these)

| Behaviour | What to expect | Spec |
|-----------|----------------|------|
| Override on a component the driver doesn't declare | Mutation rejected: `UNKNOWN_COMPONENT_CONTAINER_OVERRIDE`, lists known components; **no redeploy** | US4 Sc.1 |
| `command: []` or `args: []` | Rejected: `INVALID_CONTAINER_COMMAND` / `INVALID_CONTAINER_ARGS`; no redeploy | US4 Sc.2 |
| Non-string element (`args: [123]`) | Rejected: corresponding typed error | US4 Sc.3 |
| `command: ["sh","-c",""]` (empty-string element) | **Accepted** (mirrors Kubernetes) | US4 Sc.4 |
| Driver upgrade renames/removes an overridden component | Upgrade succeeds; block preserved, returned with `isOrphaned: true`; no value reaches any pod | US5 |
| Remove an orphaned block | Standard update-deployment without the block → disappears from reads | US5 Sc.4 |

---

## Part D — E2E verification (definition of done — Constitution §V)

Run the feature E2E to a **local PASS** and record evidence (node ID, exact command, ISO-8601 timestamp, vcluster id + kubeconfig path, verbatim `PASSED …` line):

```bash
sleep infinity | uv run pytest \
  backend/tests/e2e/test_deployment_container_overrides.py -v -s --pdb 2>&1 | tee /tmp/pdb.log
```

The test deploys `simple-app`, sets `args` (US1), sets `command` independently (US2), clears and falls back (US3), rejects invalid overrides (US4), and orphans across a driver upgrade (US5); it asserts the rendered pod container's `command`/`args` via `helpers/workloads.py::_wait_for_pod_template`. Shard marker: `shard_configuration`. Runs **dual-entrypoint** (NOT `api_only`): the UI scenario driver is extended to drive the frontend Command/Args editor, so the `[ui-chromium]` variant covers the editor too.
