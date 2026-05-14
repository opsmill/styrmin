# Quickstart: Typed `UpdateDeploymentInput`

This quickstart shows how an SDK consumer, a GraphiQL user, and the frontend deployment-edit dialog each call the post-cutover `updateDeployment` mutation.

## Python SDK

```python
from uuid import UUID
from styrmin_sdk import StyrminClient
from styrmin_sdk.models import (
    UpdateDeploymentInput,
    ComponentConfigInput,
    EnvVarInput,
    SchedulingInput,
    ResourceRequirementsInput,
    ResourceSpecInput,
    ParameterValueInput,
)

client = StyrminClient(url="https://styrmin.local/graphql", token="...")

# Add an env var on a specific component, bump CPU request, change one
# driver-defined parameter, and rename the deployment — all in one call.
task = await client.deployments.update(
    deployment_id=UUID("5f2c4f8e-..."),
    input=UpdateDeploymentInput(
        name="web-staging-v2",
        components=[
            ComponentConfigInput(
                name="web",
                env_vars=[
                    EnvVarInput(name="OTEL", value="https://otel.staging"),
                ],
            ),
        ],
        scheduling=SchedulingInput(
            resources=ResourceRequirementsInput(
                requests=ResourceSpecInput(cpu="200m"),
            ),
        ),
        parameters=[ParameterValueInput(name="replicas", value=3)],
    ),
)
print(task.id, task.status)
```

### Things that have changed vs. the pre-cutover SDK

- `client.deployments.update(...)` no longer accepts `config: dict` or `parameters: dict`. The only keyword argument besides `deployment_id` is `input: UpdateDeploymentInput`.
- Submitting `input=UpdateDeploymentInput(ip_whitelist=None)` is a **no-op** for `ip_whitelist` (omitted fields are not touched). Submitting `input=UpdateDeploymentInput(ip_whitelist=[])` is an **explicit clear**.
- `parameters` keeps **merge semantics**: the input parameters merge on top of the persisted parameters dict. Existing keys not named in the input survive. This is the documented exception to full-replacement and is asymmetric with the rest of the input on purpose (preserves pre-cutover ergonomics; see FR-006 in `spec.md`).
- Submitting two `EnvVarInput` entries with the same `name` (top-level or inside a `ComponentConfigInput`) returns `extensions.code = "DUPLICATE_ENV_VAR_NAME"`. The same goes for `ParameterValueInput` (`DUPLICATE_PARAMETER_NAME`) and duplicate `ComponentConfigInput.name` (`DUPLICATE_COMPONENT_NAME`).

## GraphiQL

```graphql
mutation UpdateMyDeployment {
  updateDeployment(
    deploymentId: "5f2c4f8e-..."
    input: {
      components: [
        {
          name: "web"
          envVars: [{ name: "OTEL", value: "https://otel.staging" }]
        }
      ]
      scheduling: {
        resources: {
          requests: { cpu: "200m" }
        }
      }
      parameters: [{ name: "replicas", value: 3 }]
    }
  ) {
    id
    status
    type
    message
    deploymentId
  }
}
```

The schema is fully introspectable: pressing `Ctrl+Space` on any field inside `input: { ... }` lists the available sub-fields. There are zero JSON-typed arguments at the top level of `updateDeployment`.

## Frontend (after codegen + dialog retarget)

```tsx
// frontend/src/components/deployment/scheduling/SchedulingConfigDialog.tsx
import { deploymentConfigToInput } from "@/lib/deployment-input";

const updateMutation = useUpdateDeploymentMutation();

async function handleSubmit(): Promise<void> {
  const scheduling = sanitizeSchedulingConfig(draft);
  // Read-modify-write: convert the existing config to the typed input shape,
  // then patch the scheduling slot. The full-replacement contract requires
  // every other field to be present (or it would be cleared).
  const input = deploymentConfigToInput(currentConfig);
  input.scheduling =
    Object.keys(scheduling).length === 0 ? null : scheduling;

  await updateMutation.mutateAsync({ deploymentId, input });
  queryClient.invalidateQueries({ queryKey: ["GetDeployment"] });
}
```

### Why the helper?

`currentConfig` (from the `Deployment` read API) carries `envVars` and `components` as **dicts** (e.g. `{ "OTEL": "https://otel.staging" }` and `{ "web": { "envVars": {...} } }`). The typed input expects **lists** (`[{ name: "OTEL", value: "https://otel.staging" }]` and `[{ name: "web", envVars: [...] }]`). The `deploymentConfigToInput` helper does this conversion in one place so every future caller doesn't have to re-derive it.

## Common errors

| `extensions.code` | What happened | How to fix |
|---|---|---|
| `INVALID_ENV_VAR_NAME` | An `envVars[*].name` (top-level or inside a `components[*]` entry) doesn't match the env-var name regex. Payload carries the offending name and the scope. | Use a name that matches `[A-Za-z_][A-Za-z0-9_]*` and is not in the reserved list. |
| `DUPLICATE_ENV_VAR_NAME` | Two `envVars` entries share the same `name` within one scope. | Deduplicate the list. The full-replacement contract means whichever entry is "first" is what would have won anyway; pick the intended one. |
| `ENV_VAR_SIZE_LIMIT_EXCEEDED` | An env-var `value` is larger than the configured cap. | Trim the value or store it elsewhere and reference it. |
| `UNKNOWN_COMPONENT_ENV_VAR` | A `components[*].name` doesn't match any component declared by the deployment's driver version. | Use `kubectl get applicationdriverversion <id> -o jsonpath='{.spec.components[*].name}'` to list the declared components. |
| `DUPLICATE_PARAMETER_NAME` | Two `parameters` entries share the same `name`. | Deduplicate. |
| `DUPLICATE_COMPONENT_NAME` | Two `components` entries share the same `name`. | Deduplicate. |
| `INVALID_CONTEXT` (from existing service-side validation) | The input is empty (no field set) or the resulting persisted dict fails Pydantic validation for a reason other than the above typed cases. | Set at least one field on the input; check the error message for the specific Pydantic complaint. |

## Verifying the cutover

After the feature lands, the following commands confirm the new shape:

```bash
# Introspect the mutation argument list
uv run styrmin export graphql-schema /tmp/schema.graphql
grep -A2 "updateDeployment(" /tmp/schema.graphql
# Expected output:
#   updateDeployment(
#     deploymentId: UUID!
#     input: UpdateDeploymentInput!
#   ): Task

# Confirm the typed input exists with the expected field count
grep -c "^  " /tmp/schema.graphql | grep -A1 "input UpdateDeploymentInput {"

# Run the propagation suite
uv run pytest backend/tests/functional/graphql/test_update_deployment_input_propagation.py -v

# Run the new E2E
uv run pytest backend/tests/e2e/test_deployment_typed_input.py -v -s --pdb
```
