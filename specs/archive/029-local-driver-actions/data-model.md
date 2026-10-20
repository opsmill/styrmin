# Data Model: Run the Actions of Driver Versions Loaded from a Local Directory

**Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

This change adds no table, no column and no Alembic revision. It reads existing columns in new places, adds one repository method, adds one kind of Prefect deployment, and adds three typed errors.

## Existing entities that the change reads

### ApplicationDriverVersion (`db/models.py`)

| Field | Used for |
|-------|----------|
| `source_type` | `"local"` or `"git"`: picks the workflow definition (R-001) and `action_directory_of` (R-003). |
| `source_path` | Local: the absolute path given on the server, stored as given. Git: the driver directory, or null for the repository root. The registration and lookup key (`directory/` tag), and the path the check step reads in the Job. |
| `content_hash` | Local: the full SHA-256 provenance fingerprint. Passed to the check step as the expected value; its first 7 characters are the `fingerprint/` tag. |
| `source_commit_sha` | Git: the provenance fingerprint; first 7 characters in the `fingerprint/` tag. Unchanged. |
| `source_repository`, `source_branch` | Git: the load command in the `ActionNotRegisteredError` message. |
| `application_supported_versions` | The `version/` tag of the registration and lookup. |
| `version` | The driver version label in error messages (`format_driver_version_label`). |

Validation rule added at load time (R-005): when `source_type == "local"` and the driver declares actions, `source_path` must not contain `{` or `}`. The load raises `DriverLoadingError` otherwise.

### Action (`db/models.py`)

| Field | Used for |
|-------|----------|
| `name` | The action named in `ActionNotRegisteredError`. |
| `hook`, `mode` | Which hook and mode pairs a driver version declares. Hook resolution looks up only declared pairs. |
| `application_driver_version_id` | `ActionRepository.list_by_driver_version`. |

New repository method:

```python
class ActionRepository(BaseRepository[Action], ABC):
    @abstractmethod
    async def list_by_driver_version(self, driver_version_id: UUID) -> list[Action]: ...
```

Returns the declared actions of one driver version, ordered by `name`.

### Task (`domain/models.py`)

The request check of R-009 saves a task without a flow run, as `delete_deployment` does:

| Field | Value |
|-------|-------|
| `type` | `TaskType.UPGRADE_INSTANCE` |
| `deployment_id` | The deployment of the request. |
| `status` | `TaskStatus.FAILED` |
| `message` | The `ActionNotRegisteredError` message. |
| `prefect_flow_run_id` | `None` |
| `instance_id` | `None`: no instance is created. |
| `started_by_step_id` | The request's `startedByStepId`, when an action started it. |

### Step (`domain/models.py`, `services/steps/recorder.py`)

| Where | Step key | Status | Error |
|-------|----------|--------|-------|
| Request check (R-009) | `hook:upgrade:<mode>` of the error | `failed` | `ActionNotRegisteredError: <message>` |
| `apply_state` planning (R-008) | `plan` | `succeeded` | — |
| `apply_state` planning (R-008) | `hook:<hook>:<mode>` of the error | `failed` | `ActionNotRegisteredError: <message>` |
| Action Job check (R-001, R-002) | the hook step that ran the action | `failed` | `RuntimeError: Deployment flow run <id> crashed: <check message> (<Prefect state message>)` |

## Prefect deployment of a local driver version's action (external record)

One per declared action, in the work pool `user-work-pool`. Fields that differ from a git action's deployment are marked.

| Field | Value |
|-------|-------|
| Flow name | `User Action: <action name>` |
| Deployment name | `User Action: <action name> (<driver name>@<short content_hash> <12-hex digest of source_path>)` |
| Tags | `application/<driver name>`, `version/<supported versions>`, `hook/<hook>`, `mode/<mode>`, `fingerprint/<short content_hash>`, `directory/<source_path>` |
| Entrypoint | `actions.py:<function>`, from the action's `location` |
| Pull steps (differs) | One step: `styrmin_backend.workflows.local_driver.check_local_driver` with `directory`, `content_hash`, `spec_file`, `values_template`, `actions_file` |
| Job variables | `{"image": <action image>}` when the action sets `image:`; none otherwise |

A git action's deployment is unchanged: pull steps `git_clone`, then `set_working_directory` for a driver directory ([ADR-079](../../dev/adr/0079-driver-actions-import-only-from-their-driver-directory.md), [ADR-080](../../dev/adr/0080-action-deployments-keyed-by-driver-directory.md)).

## Value objects (new, service layer)

```python
@dataclass(frozen=True)
class ActionRegistrationKey:
    application: str            # driver name
    version: str                # application_supported_versions
    fingerprint: str | None     # short_fingerprint(content_hash, source_commit_sha)
    directory: str | None       # action_directory_of(source_type, source_path)


@dataclass(frozen=True)
class UpgradeHookFlows:
    core: UUID
    pre: UUID | None
    post: UUID | None
```

`ActionRegistrationKey` is built once from a driver version row (hooks) or from a loaded driver object (registration), so both use the same key (FR-006).

## Typed errors

All three subclass `DriverError` (`services/driver/exceptions.py`). Fields and messages are in [contracts/errors.md](contracts/errors.md).

| Error | Raised by | Requirement |
|-------|-----------|-------------|
| `DriverFilesNotFoundError` | `check_local_driver` in the action's Job | FR-004 |
| `DriverFingerprintMismatchError` | `check_local_driver` in the action's Job | FR-003 |
| `ActionNotRegisteredError` | `resolve_hook_flow` (server and `apply_state` flow) | FR-005 |

## State after each failure

| Failure | Task | Deployment | Active instance | Cluster | How to retry |
|---------|------|------------|-----------------|---------|--------------|
| Request check finds a missing registration (upgrade) | new task, `failed`, no flow run | unchanged (version, driver binding, status) | unchanged | unchanged | Load the driver again, then send the same request. |
| `apply_state` planning finds a missing registration (create, or a registration deleted after the request) | `failed` | `failed` | the new instance, `failed` | unchanged | Create: load the driver again, delete the deployment and create it again. Upgrade: as for any failed upgrade. |
| Check in the action's Job fails (FR-003, FR-004) | `failed` | `failed` | the new instance, `failed` | Create: nothing applied when `setup`/`pre` fails. Upgrade: the components that earlier hooks changed. | Rebuild the image or load the driver again, then as for any failed create or upgrade. |
