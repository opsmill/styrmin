# Research: Anonymous Daily Telemetry from the Styrmin Server

**Feature**: `020-backend-telemetry` | **Spec**: [spec.md](spec.md) | **PRD**: [#274 (comment)](https://github.com/opsmill/styrmin/issues/274#issuecomment-6069930520)

Each decision lists what was chosen, why, and what was rejected. File references are relative to the repository root and were read on 2026-10-08.

## Facts that shaped the design

- **INTERNAL flows run in the task worker, not in the server pod.** `PrefectManager.setup_deployments` sends INTERNAL flows to `styrmin-work-pool` (`backend/styrmin_backend/workflows/manager.py:177-180`), a `process` pool (`workflows/catalogue.py:84-90`). The pool is served by the `task-worker` Deployment (`helm/styrmin/templates/styrmin-server/task-worker-deployment.yaml:54-59`) and by the `task-worker` service in `docker-compose.yml:16`. Each flow run is a subprocess that inherits the worker's environment. The server and the task worker both load the shared ConfigMap with `envFrom` (`deployment.yaml:59-61`, `task-worker-deployment.yaml:60-62`).
- **Catalogue registration is idempotent.** On every start the server calls `PrefectManager.initialize()` (`server/app.py:58-59`), which calls `create_deployment` for each catalogue entry. Prefect 3.8.6 upserts on `(flow_id, name)`, deletes future auto-scheduled runs and recreates the schedule in one transaction (`prefect/server/models/deployments.py`, `create_deployment`). Scheduled runs carry the idempotency key `scheduled {deployment.id} {schedule.id} {date}`. So restarts and extra server replicas leave one deployment with one schedule, and Prefect gives each flow run to one worker only. FR-012 needs no extra code for this.
- **A run that is due while the task worker is down still runs later.** A worker fetches every flow run in a `SCHEDULED` state type whose time has passed (`prefect/server/database/query_components.py:215-227`), and `Late` is a `SCHEDULED` state type. Without a guard, a report missed at 02:43 is sent when the worker comes back, which contradicts the spec edge case "the missed report is not sent later" (D14).
- **`STYRMIN_WORKFLOW_ENABLE` has no effect.** It is declared in `config.py:111` and rendered by the chart (`configmap.yaml:17`), but no code reads `workflow.enable`. The PRD edge case "Workflows are turned off: the daily flow does not run" is therefore not true of the current code (D15).
- **No running code knows the Styrmin release version.** The release workflow bumps only the root `pyproject.toml` (`name = "styrmin-mvp"`, `version = "0.1.47"`) and `helm/*/Chart.yaml` (`.github/workflows/release.yml:100-112`). The root project has `[tool.uv] package = false`, so it is never installed and `importlib.metadata.version("styrmin-mvp")` raises `PackageNotFoundError`. `styrmin-backend` and `cli` stay at `0.1.0` (`backend/pyproject.toml:3`, `cli/pyproject.toml:3`). The Docker image copies the root `pyproject.toml` to `/source/pyproject.toml` (`docker/Dockerfile`, `COPY uv.lock pyproject.toml ./`) and installs the workspace members from `/source` (D6).
- **The chart has no field for extra environment variables** on the server or the task worker. Only the agent subchart has `extraEnv` (`helm/agent/values.yaml:67`).
- **E2E installs the chart once per session** with `backend/tests/e2e/fixtures/styrmin-values.yaml` (`backend/tests/e2e/conftest.py:621-658`). A sink in the pytest process listens on `127.0.0.1` and cannot be reached from a pod; `chart_server` (`conftest.py:376-428`) is the existing pattern for a test server inside the vcluster.

## D1: Modules and where they live

**Decision**: Follow the PRD module table, with these locations:

| Module | Location |
|---|---|
| Telemetry settings | `TelemetrySettings` in `backend/styrmin_backend/config.py` |
| Install ID store | model `Installation` in `db/models.py`, `repository/installation.py`, one Alembic revision |
| Count and driver-usage queries | new methods on the existing cluster, environment, deployment and driver-version repositories |
| Payload builder | `services/telemetry/payload.py` |
| Envelope and sender | `services/telemetry/sender.py` |
| Effective state and startup log line | `services/telemetry/state.py` |
| Daily flow | `workflows/templates/telemetry.py`, catalogue entry `PrefectAction.SEND_TELEMETRY_REPORT` |
| `styrmin telemetry show` | `cli/telemetry.py`, registered in `cli/app.py` |
| Helm value | `helm/styrmin/values.yaml`, `templates/configmap.yaml` |

**Rationale**: Constitution §III requires service → repository → database. The counts are new aggregate queries, so they go into the repositories that own those tables instead of a telemetry-only repository that would query other modules' tables. A `services/telemetry/` package keeps the feature in one place, as `services/auth/` does for sessions.

**Alternatives considered**:
- One `TelemetryRepository` with all four queries: rejected, because it would read tables owned by four other repositories.
- Computing counts from `get_all()`: rejected, because `get_all()` eager-loads relationships and would load every deployment with its instances to count them.

## D2: One payload builder for the flow and the CLI

**Decision**: `build_report_data(uow) -> dict` in `services/telemetry/payload.py` builds the `data` object. The daily flow and `styrmin telemetry show` both call it, so the command prints exactly what the flow sends (FR-013).

**Rationale**: Two code paths would let the printed and sent data differ, which would defeat the purpose of the command.

## D3: Envelope and checksum — the server has its own copy

**Decision**: `services/telemetry/sender.py` has its own `checksum(data)` and `build_envelope(data)` with `kind = "styrmin"`. A unit test asserts that the server's checksum equals `styrminctl.telemetry.envelope.checksum` for the same `data`, so the two cannot drift.

**Rationale**: The backend imports nothing from `styrminctl` today, and `CONTEXT.md` defines the CLI as a thin client over GraphQL. Importing the CLI package from the server would make the server depend on its own client for 15 lines of code. The test keeps the algorithm identical, which is what FR-007 needs.

**Alternatives considered**:
- Import `styrminctl.telemetry.envelope` from the backend: rejected, it reverses the dependency between server and client.
- Move the envelope into `styrmin-sdk` or a new shared package: rejected, the SDK is the GraphQL client and a new workspace member is out of proportion for two functions.

## D4: Default endpoint URL

**Decision**: `https://telemetry-endpoints.cloudflare-096.workers.dev/styrmin`. [CLAUDE RECOMMENDED – based on the `styrminctl` default `https://telemetry-endpoints.cloudflare-096.workers.dev/styrminctl` in `cli/src/styrminctl/telemetry/config.py:17`, which uses one path per reporting product]

**Rationale**: The PRD leaves the URL open. A path per `kind` keeps the two report streams apart on the ingestion side. The URL is one constant and can be changed before the release without other code changes. Whether the ingestion endpoint accepts this path is not known; the owner of the endpoint must confirm it before the release (recorded in [plan.md](plan.md), "Release prerequisite").

**Alternatives considered**:
- The same URL as `styrminctl`, distinguished by `kind`: possible if the ingestion endpoint routes on `kind`, which is not known.

## D5: `payload_format` value

**Decision**: `"1.0"`, independent of the `styrminctl` value. It changes only when the `data` keys or their meaning change.

**Rationale**: `kind` already separates the two streams, so each stream versions its own format. Starting at `"1.0"` matches the first `styrminctl` format and the wire-format contract of spec 015, which treats the value as an opaque string.

## D6: How the server finds the Styrmin version

**Decision**: `styrmin_version` is the `project.version` of the workspace root `pyproject.toml`, located as `Path(styrmin_backend.__file__).resolve().parents[2] / "pyproject.toml"` and accepted only when its `project.name` is `styrmin-mvp`. The file is parsed with the standard library `tomllib`. If the file is missing or does not match, the value is `"unknown"`, and the builder logs this at debug level.

**Rationale**: This file is the only place the release workflow writes the version that also exists inside the image (`/source/pyproject.toml`, next to the editable `/source/backend`). It works in the image, in docker-compose (same image) and in a development checkout. It needs no CI change and no Helm change.

**Alternatives considered**:
- Pass `.Chart.AppVersion` or the image tag as an environment variable from the chart: rejected, because an operator who sets `image.tag` would report the chart version instead of the running code's version, and docker-compose has no chart.
- Make the release workflow also bump `backend/pyproject.toml`: rejected for this feature, because it is a CI/CD workflow change (governance gate) and it would also change the `version` that INTERNAL Prefect deployments carry.
- `importlib.metadata.version("styrmin-backend")`: rejected, it is always `0.1.0`.

**Observation, out of scope**: `styrminctl` reports `version("cli")` (`cli/src/styrminctl/telemetry/event.py:98`), which is always `0.1.0`, so CLI reports cannot tell versions apart either. This feature does not change `styrminctl` (spec "Out of Scope"). [CLAUDE RECOMMENDED – based on this finding] File a separate issue for it.

## D7: Settings and the effective state

**Decision**: A `TelemetrySettings(BaseSettings)` group with `env_prefix="STYRMIN_TELEMETRY_"`, fields `enabled: bool = True` and `endpoint: str = DEFAULT_ENDPOINT`, plus `do_not_track: str | None` read from `DO_NOT_TRACK` through `validation_alias`. A blank `endpoint` falls back to the default. A method `disabled_by() -> str | None` returns `"STYRMIN_TELEMETRY_ENABLED=false"`, `"DO_NOT_TRACK=1"` or `None`, checked in that order. The group is mounted as `Settings.telemetry` and exposed as `SETTINGS.telemetry`, like the other groups. The full table is in [contracts/configuration.md](contracts/configuration.md).

**Rationale**: pydantic-settings already supports reading one field from a variable without the prefix (`validation_alias`; `config.py` already imports `AliasChoices`), so no extension or workaround is needed. `DO_NOT_TRACK` counts only when it is exactly `1`, as in `styrminctl` (`cli/src/styrminctl/telemetry/eligibility.py:130`).

## D8: Sending, the 10-second limit and failure handling

**Decision**:
- The sender posts with `httpx.AsyncClient` inside `asyncio.timeout(10)`. The `asyncio` deadline covers DNS, connect, write and read together.
- A response outside 2xx, a timeout, or any `httpx` or OS error counts as a failed send. The sender returns `False` and logs one debug line with the error class and status code. It never raises.
- The flow wraps its whole body in `try/except Exception` and logs anything unexpected at debug level, so the run always ends `Completed` (FR-008, PRD module table: "always ends `Completed`").
- Logging inside the flow uses Prefect's `get_run_logger()`, as `session_cleanup.py` does. Prefect's default level is INFO, so debug lines do not appear unless an operator lowers the level.

**Rationale**: An `httpx` timeout applies to each phase separately, so a slow server that sends one byte at a time could exceed 10 seconds in total. ADR-047 found the same problem for `styrminctl`. In an async flow, `asyncio.timeout` gives a hard total limit without a thread. `httpx` needs no extension for this.

**Note on SC-004**: Prefect itself logs the flow-run state change ("Finished in state Completed()") at INFO for every flow, including the session cleanup flow. That line is about the flow run, not the report, so it does not break SC-004.

## D9: Driver entries are merged by name, version and source type

**Decision**: The repository returns one row per application driver version with its driver name, version, source type and the number of live deployments bound to it (LEFT OUTER JOIN on `deployment.application_driver_version_id` with `deployment.deleted_at IS NULL`, GROUP BY the driver version). The builder merges rows with the same `(name, version, source_type)` by adding their counts, and sorts the entries by `name`, `version`, `source_type`.

**Rationale**: Two driver versions can share name, version and source type and differ only in repository, branch, path or fingerprint (`uq_application_driver_version_identity`, `db/models.py`). FR-002 removes exactly those fields, so the entries would be identical except for the count, and the endpoint could not tell them apart. Merging gives one entry per value the maintainer can read. Sorting makes the data, and so the checksum, the same for the same database state.

**Alternatives considered**:
- One entry per row: rejected, it produces duplicate-looking entries.
- Add the provenance fingerprint to tell rows apart: rejected, FR-001 fixes the entry keys and the fingerprint is not among them.

## D10: Install ID store

**Decision**:
- New model `Installation` (table `installation`): `id` integer primary key with `CHECK (id = 1)`, `install_id` UUID not null, `created_on` timestamp with time zone, server default `now()`. It does not inherit `StyrminModel`, because that adds a UUID primary key and `updated_on`, which a single fixed row does not need.
- `InstallationRepository.get_or_create_install_id()` inserts `(1, uuid4())` with `ON CONFLICT (id) DO NOTHING`, then selects the row. The insert picks the PostgreSQL or SQLite dialect, as `services/auth/bootstrap.py:36-87` does for the admin user.
- The server calls it during startup, after the admin bootstrap and before `PrefectManager.initialize()` (`server/app.py`, between lines 55 and 58). The flow and `styrmin telemetry show` call the same method, so they also work against a database where the row is missing.
- One Alembic revision `add_installation` with `down_revision = "c2ff6dba5ffd"` (the current head) creates the table; the downgrade drops it. The PRD records the approval of this database change on 2026-10-08.

**Rationale**: `CHECK (id = 1)` with a fixed key makes a second row impossible, and `ON CONFLICT DO NOTHING` lets two replicas that start at the same time agree on one ID without a lock. The ID is created whether telemetry is on or off (FR-014). `init_db()` only runs `create_all` for a fresh database, so the revision is required for existing databases (ADR-001).

**Alternatives considered**:
- A UUID primary key that is the install ID: rejected, it cannot stop a second row from being inserted.
- Store the ID in a file or a Kubernetes Secret: rejected by the PRD ("One install is one Styrmin database").

## D11: Helm values

**Decision**: Add `styrmin.telemetry.enabled` (default `true`) and `styrmin.telemetry.endpoint` (default `""`) to `helm/styrmin/values.yaml`. `configmap.yaml` renders `STYRMIN_TELEMETRY_ENABLED` always and `STYRMIN_TELEMETRY_ENDPOINT` only when `endpoint` is not empty. Both pods receive them through `envFrom`.

**Rationale**: The ConfigMap is the only path that reaches the task worker, where the flow runs. `endpoint` is not in the PRD's list, but E2E must point the server at its sink (FR-011), and the chart has no other way to set an environment variable. It also lets operators send reports through their own relay. [CLAUDE RECOMMENDED – based on the missing `extraEnv` field in the chart and on FR-011]

**Alternatives considered**:
- Add a general `extraEnv` to both templates: rejected for this feature, it is a larger chart change than the feature needs.

## D12: The E2E sink runs inside the vcluster

**Decision**: A new fixture `telemetry_sink` (module scope) builds a small image from `backend/tests/e2e/fixtures/telemetry-sink/` (`python:3.14-slim` and a standard-library HTTP server), deploys it as Deployment and Service `telemetry-sink` in namespace `default`, and port-forwards to it, following `chart_server`. The sink answers `POST /report` by storing the body and `GET /reports` with the list of stored bodies. `styrmin-values.yaml` sets `styrmin.telemetry.endpoint: http://telemetry-sink.default.svc.cluster.local:8080/report`.

**Rationale**: The endpoint must be set when the chart is installed, because changing the environment later restarts the pods and breaks the shared port-forward. A fixed cluster DNS name can be set before the sink exists; a run without the sink fails with "connection refused", which the flow ignores. The `python:3.14-slim` base is already in the local Docker cache, because the Styrmin image builds from it.

**Alternatives considered**:
- Reuse the `styrminctl` sink in the pytest process: rejected, a pod cannot reach `127.0.0.1` of the test host.
- Read reports from the sink pod's log: rejected, parsing logs is less reliable than a `GET` endpoint.

## D13: The E2E test triggers the flow through the Prefect API

**Decision**: The test port-forwards to the `prefect-server` Service, reads the deployment `send_telemetry_report/send_telemetry_report` by name, calls `create_flow_run_from_deployment`, and polls `read_flow_run` until the run is final, as `test_worker_death_recovery.py:74-170` does. It asserts the final state is `COMPLETED`.

**Rationale**: No GraphQL mutation or CLI command starts a catalogued flow, and the PRD rules out new GraphQL surface. The Prefect API is the interface the scheduler itself uses.

## D14: Runs that start more than one hour late do not send

**Decision**: The flow compares `prefect.runtime.flow_run.scheduled_start_time` with the current time. When the run starts more than one hour after its scheduled time, it logs one debug line and ends `Completed` without building or sending a report.

**Rationale**: This makes the spec edge case "the missed report is not sent later" true, and keeps FR-012 "at most one report a day" when a late run would otherwise be followed by the next day's run a few hours later. A run started on demand has a scheduled time of "now", so the E2E trigger is not affected.

**Dependency evaluation**: Prefect has no deployment or work-pool setting that drops runs that are too late; the late-runs service only marks them `Late`. Server-side orchestration rules are not pluggable from a client. An upstream feature request would take longer than this feature, and the check needs three lines in the flow, so the gap is filled in the flow.

## D15: `STYRMIN_WORKFLOW_ENABLE`

**Decision**: No change to `STYRMIN_WORKFLOW_ENABLE`. The spec edge case is corrected to say that the setting has no effect in the current code, so it does not stop reports, and that operators turn telemetry off with the telemetry settings.

**Rationale**: Making the telemetry flow read a setting that nothing else reads would give it a meaning for one flow only. Fixing the setting for all workflows is outside this feature.

## D16: Time of day of the daily run

**Decision**: Cron `43 2 * * *`, read by Prefect as UTC.

**Rationale**: The PRD leaves the time open. 02:43 UTC is outside working hours in Europe and the Americas, does not overlap the session cleanup at 03:17 UTC, and is not on the hour, when other scheduled jobs often start. All installs report at the same minute; at the expected number of installs this is a small load for the ingestion endpoint.

**Alternatives considered**:
- A minute derived from the install ID, to spread the load: rejected for v1, because the catalogue is built before the database is read and the cron would have to be computed at registration time.

## D17: Startup log line

**Decision**: `services/telemetry/state.py` has `startup_message(settings) -> str`. `app_initialization` logs it with loguru at INFO right after the logger is configured (`server/app.py`, after line 48), so it appears even when the database is not ready yet. The exact text is in [contracts/configuration.md](contracts/configuration.md).

**Rationale**: FR-010 asks for the line on every start. With more than one uvicorn worker (`styrmin server start --workers N`) each process logs it once; the default is one worker.

## D18: Development and test installs

**Decision**:
- `docker-compose.yml`: add `STYRMIN_TELEMETRY_ENABLED: "false"` to the `server` and `task-worker` services. `invoke dev` starts this file, so it is covered.
- `dev/local/demo-values.yaml`: add `styrmin.telemetry.enabled: false`. [CLAUDE RECOMMENDED – based on PRD user story 9; the PRD lists docker-compose and `invoke dev` but not the local demo, which is also a development install]
- E2E: the sink endpoint from D12.

**Rationale**: FR-011 and PRD user story 9.

## D19: Tests

**Decision**:
- Unit tests for the settings (D7), the install ID store against SQLite and PostgreSQL (D10), the repository queries, the payload builder (exact key set, merged and sorted drivers, tombstoned deployments excluded, no forbidden keys), the sender (2xx, 4xx, 5xx, connection refused, a server that never answers, checksum against `styrminctl`), the flow (off by each setting means no request; late run means no request; exceptions end `Completed`), the startup message, the catalogue entry's cron schedule (through `to_deployment()`, as `test_git_source_commit_pinning.py:112-152` does), and the Helm ConfigMap (`helm template` with and without the values).
- A migration test for the new revision, following `tests/unit/db/test_steps_migration.py`.
- One `api_only` E2E test in a new file `backend/tests/e2e/test_server_telemetry.py`, marked `ci` and `shard_general`, that uses `deployed_simple_app` (booted by ten other files in the same shard, so no extra stack). It runs `styrmin telemetry show` in the server pod, triggers the flow (D13), and asserts that the sink received exactly one new report with the FR-006 keys, `kind: "styrmin"`, a valid checksum, and `data` equal to the command output.

**Rationale**: The PRD testing decisions. The E2E file is new, but it adds no heavy fixture: it reuses the Styrmin install and the simple-app deployment that the shard already boots, which is the "sibling sharing its session fixture" form in `dev/guides/e2e-deployment-sharing.md`. The test compares the command output with the received data instead of fixed numbers, because other tests in `shard_general` add and remove deployments.
