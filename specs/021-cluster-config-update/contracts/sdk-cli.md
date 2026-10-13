# Contract: SDK `clusters.update` and `styrminctl clusters update`

**Feature**: [../spec.md](../spec.md) | **Decisions**: [../research.md](../research.md) D2, D3

## SDK

```python
class ClusterResource(BaseResource):
    async def update(
        self,
        config: Mapping[str, Any],
        cluster_id: str | UUID | None = None,
        cluster_name: str | None = None,
        *,
        dry_run: bool = False,
    ) -> UpdateClusterUpdateCluster: ...
```

- `config` is a dict, like `create()`, with snake_case or camelCase keys. `cluster_update_input(config)` refuses every unknown key at any depth with a `ValueError` naming its path, converts the stored enum values that `get()` returns (`http`, `NoSchedule`) to the GraphQL names, and returns the `UpdateClusterInput` variables. This replaced a typed `UpdateClusterInput` parameter after the review of 2026-10-12: the generated model drops unknown keys silently, and refused the stored enum values.
- The call waits up to `UPDATE_CLUSTER_TIMEOUT_SECONDS` (600 s), because the server starts every redeploy before it answers.
- Exactly one of `cluster_id` and `cluster_name` is expected; the server refuses both or neither.
- GraphQL errors raise the existing typed SDK exceptions (`_check_graphql_errors`).

## CLI

```text
styrminctl clusters update [NAME] [--id UUID] --config JSON|@FILE [--dry-run]
```

| Argument | Meaning |
|---|---|
| `NAME` | Cluster name. |
| `--id` | Cluster id. Exactly one of `NAME` and `--id`. |
| `--config` | Required. The whole cluster config, inline JSON or `@path`, in the same snake_case shape as `clusters create --config`. camelCase keys are accepted too. |
| `--dry-run` | Check the config and list the deployments that would be redeployed, without saving. |

Behaviour:

1. Parse `--config` with `parse_json_argument`.
2. Refuse a value that is not a JSON object, and unknown keys at any depth with the SDK's `cluster_update_input`; the error names each unknown key path and the command exits non-zero without connecting (research D3).
3. Call `sdk.clusters.update(config, ..., dry_run=...)`.
4. On success, print `Cluster '<name>' updated (id: <id>)` (or that nothing was saved, for a dry run), then the deployments redeployed with their task ID, waiting for a dedicated ingress controller, skipped for a restore and failed to start, the controller actions and the failed environments, the number of deployments already at their config, and `styrminctl tasks get TASK_ID` to follow a redeploy. When something failed, say to run the command again. The first version printed the stored config and pointed to `styrminctl tasks list`, which has no filter (review of 2026-10-12).
5. On a transport timeout, say that the server can still be saving the config.

Errors go through `styrmin_error_handler` (existing): the validation error, the not-found error, the clone-in-progress error and the permission error print their messages and exit non-zero.

### `styrminctl clusters get` (changed)

The `config` value is printed as JSON (`json.dumps`, sorted keys) instead of the Python `str()` of the dict. `--json` prints only the config, indented, so an administrator can save it to a file and edit it (critique P2); the table cuts long values.

## CLI tests

`cli/tests/test_clusters.py`:

- the parsed file reaches `sdk.clusters.update` as a dict, for snake_case and camelCase files;
- the update result is printed: redeployed deployments with their task, waiting, failed to start, failed environments, and the retry line;
- an unknown top-level key and an unknown nested key (`dedicated_ingress.servce`) are refused before any SDK call;
- name and `--id` are mutually exclusive, and one is required.
- `clusters get` prints the config as valid JSON (parsed back with `json.loads` in the test), and `clusters get --json` prints only the config.

The unknown-key, enum-conversion and dry-run cases are also covered in `python_sdk/tests/test_clusters.py`.
