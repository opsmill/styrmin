# Contract: SDK `clusters.update` and `styrminctl clusters update`

**Feature**: [../spec.md](../spec.md) | **Decisions**: [../research.md](../research.md) D2, D3

## SDK

```python
class ClusterResource(BaseResource):
    async def update(
        self,
        input: UpdateClusterInput,
        cluster_id: str | UUID | None = None,
        cluster_name: str | None = None,
    ) -> UpdateClusterUpdateCluster: ...
```

- `UpdateClusterInput` is the generated Pydantic model, exported from `styrmin_sdk` like `UpdateEnvironmentInput`. It accepts snake_case or camelCase keys (`populate_by_name=True`).
- Exactly one of `cluster_id` and `cluster_name` is expected; the server refuses both or neither.
- GraphQL errors raise the existing typed SDK exceptions (`_check_graphql_errors`).

## CLI

```text
styrminctl clusters update [NAME] [--id UUID] --config JSON|@FILE
```

| Argument | Meaning |
|---|---|
| `NAME` | Cluster name. |
| `--id` | Cluster id. Exactly one of `NAME` and `--id`. |
| `--config` | Required. The whole cluster config, inline JSON or `@path`, in the same snake_case shape as `clusters create --config`. camelCase keys are accepted too. |

Behaviour:

1. Parse `--config` with `parse_json_argument`.
2. Refuse unknown keys at any depth with `validate_input_strict(UpdateClusterInput, data)`; the error names each unknown key path and the command exits non-zero without calling the server (research D3).
3. Call `sdk.clusters.update(...)`.
4. On success, print `Cluster '<name>' updated (id: <id>)` and the stored config, like `clusters get`.

Errors go through `styrmin_error_handler` (existing): the validation error, the not-found error, the clone-in-progress error and the permission error print their messages and exit non-zero.

## CLI tests

`cli/tests/test_clusters.py`:

- the parsed file reaches `sdk.clusters.update` as an `UpdateClusterInput`, for snake_case and camelCase files;
- an unknown top-level key and an unknown nested key (`dedicated_ingress.servce`) are refused before any SDK call;
- name and `--id` are mutually exclusive, and one is required.
