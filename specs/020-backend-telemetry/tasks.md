---

description: "Task list for anonymous daily telemetry from the Styrmin server"
---

# Tasks: Anonymous Daily Telemetry from the Styrmin Server

**Input**: Design documents from `specs/020-backend-telemetry/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: Required. Constitution §V requires unit tests for new functionality and an E2E test observed to pass locally, with evidence recorded in `specs/020-backend-telemetry/e2e-evidence.md`. The PRD names the modules that get their own unit tests; `styrmin telemetry show` and the daily flow wiring are covered by the E2E test. No GraphQL propagation test is needed, because the GraphQL schema does not change.

**Organization**: Tasks are grouped by user story so each story can be built and tested on its own after the foundational phase.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an unfinished task)
- **[Story]**: The user story the task belongs to (US1 to US6 in [spec.md](spec.md))
- Paths are relative to the repository root. Research decisions are cited as D1 to D19 ([research.md](research.md)); critique findings as E2, E3, P2 and so on ([critiques/critique-20261008.md](critiques/critique-20261008.md)).

## E2E evidence rule (applies to every "Run … and record evidence" task)

Run each E2E node with `--pdb` (in a non-interactive shell: `sleep infinity | uv run pytest <node> -v -s --pdb 2>&1 | tee /tmp/pdb.log`). Run the `api-chromium` variant only (`-k api-chromium`), in a session of its own. For each new or changed node, append to `specs/020-backend-telemetry/e2e-evidence.md`: (a) the pytest node ID, (b) the exact command, (c) the ISO 8601 time of the passing run, (d) the vCluster fixture ID and kubeconfig path under `/tmp/pytest-of-*/pytest-*/`, (e) the verbatim `PASSED …` line. A node that has only been skipped, or never run against a cluster, is not done.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Packages, evidence file and baseline

- [X] T001 Confirm the environment: run `uv sync` and `uv run invoke pre-commit-install`, check that `helm`, `docker` and `vcluster` are on `PATH`, and confirm the Alembic head is `c2ff6dba5ffd` by listing `backend/styrmin_backend/db/migrations/versions/` (T006 uses it as `down_revision`)
- [X] T002 [P] Create empty packages `backend/styrmin_backend/services/telemetry/__init__.py` and `backend/tests/unit/services/telemetry/__init__.py`
- [X] T003 [P] Create `specs/020-backend-telemetry/e2e-evidence.md` with a header and an empty table (columns: node ID, command, passing time, vCluster ID and kubeconfig, PASSED line)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Settings, install ID storage, count queries and the payload builder, which the daily flow (US1, US2, US4) and `styrmin telemetry show` (US3) both use

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Settings (D7, [contracts/configuration.md](contracts/configuration.md))

- [X] T004 Add `TelemetrySettings(BaseSettings)` to `backend/styrmin_backend/config.py`: `model_config = SettingsConfigDict(env_prefix="STYRMIN_TELEMETRY_")`; module constant `DEFAULT_TELEMETRY_ENDPOINT = "https://telemetry-endpoints.cloudflare-096.workers.dev/styrmin"`; fields `enabled: bool = True`, `endpoint: str = DEFAULT_TELEMETRY_ENDPOINT` (a validator turns a blank or whitespace value into the default), `do_not_track: str | None = Field(default=None, validation_alias="DO_NOT_TRACK")`; method `disabled_by() -> str | None` that returns `"STYRMIN_TELEMETRY_ENABLED=false"` when `enabled` is false, else `"DO_NOT_TRACK=1"` when `do_not_track == "1"`, else `None`. Mount it as `telemetry: TelemetrySettings = Field(default_factory=TelemetrySettings)` in `Settings` and add a `telemetry` property to `ConfiguredSettings`, following the other groups
- [X] T005 [P] Unit tests in `backend/tests/unit/test_telemetry_settings.py` (use `monkeypatch.setenv`/`delenv`): defaults give `enabled=True`, the default endpoint and `disabled_by() is None`; `STYRMIN_TELEMETRY_ENABLED=false` and `=0` give `"STYRMIN_TELEMETRY_ENABLED=false"`; `DO_NOT_TRACK=1` gives `"DO_NOT_TRACK=1"`; `DO_NOT_TRACK=true` and `=0` give `None`; both set give `"STYRMIN_TELEMETRY_ENABLED=false"`; `STYRMIN_TELEMETRY_ENDPOINT=""` and `"  "` give the default; `STYRMIN_TELEMETRY_ENDPOINT=http://sink/report` is kept; `load(config_data={"telemetry": {"enabled": False}})` gives `"STYRMIN_TELEMETRY_ENABLED=false"`

### Install ID storage (D10, [data-model.md](data-model.md))

- [X] T006 Add model `Installation(SQLModel, table=True)` to `backend/styrmin_backend/db/models.py` (not `StyrminModel`): `id: int` primary key, `install_id: UUID` not null, `created_on` timestamp with time zone with `server_default=func.now()` and not null; `__table_args__ = (CheckConstraint("id = 1", name="ck_installation_single_row"),)`. Then add the Alembic revision `backend/styrmin_backend/db/migrations/versions/<new 12-hex id>_add_installation.py` with `down_revision = "c2ff6dba5ffd"`, a docstring citing spec 020 and issue #274, `upgrade()` creating table `installation` with the check constraint, and `downgrade()` dropping it
- [X] T007 [P] Migration round-trip test `backend/tests/unit/db/test_installation_migration.py`, following `backend/tests/unit/db/test_steps_migration.py` (PostgreSQL through `postgres_url` and SQLite): upgrade to the new revision creates `installation` with columns `id`, `install_id`, `created_on`; inserting a second row with `id = 2` fails on the check constraint; downgrade to `c2ff6dba5ffd` removes the table
- [X] T008 Create `backend/styrmin_backend/repository/installation.py`: abstract `InstallationRepository` with `get_or_create_install_id() -> UUID`, and `SQLModelInstallationRepository(session)` that inserts `(id=1, install_id=uuid4())` with `ON CONFLICT (id) DO NOTHING`, picking the PostgreSQL or SQLite `insert` by `session.bind.dialect.name` and suppressing the same warnings as `_build_insert` in `backend/styrmin_backend/services/auth/bootstrap.py:36-87`, then selects and returns `install_id` of row `1`. Register it in `backend/styrmin_backend/services/unit_of_work.py`: attribute `installation: InstallationRepository` on `UnitOfWork` and `self.installation = SQLModelInstallationRepository(session=self.session)` in `SqlModelUnitOfWork.__aenter__`
- [X] T009 [P] Repository tests `backend/tests/unit/repository/test_installation_repository.py` with the SQLite `session` fixture of `backend/tests/unit/repository/conftest.py`, plus one PostgreSQL case through `postgres_url` and `SQLModel.metadata.create_all`: the first call returns a UUID and creates one row; a second call, also from a second session on the same database, returns the same UUID; the table still has one row

### Count and driver-usage queries (D1, D9)

- [X] T010 Add read queries: `count() -> int` to `ClusterRepository`/`SQLModelClusterRepository` in `backend/styrmin_backend/repository/cluster.py` and to `EnvironmentRepository`/`SQLModelEnvironmentRepository` in `backend/styrmin_backend/repository/environment.py` (`SELECT COUNT(*)`, no eager loading); `count_live() -> int` to `DeploymentRepository` and its SQLModel class in `backend/styrmin_backend/repository/deployment.py` (`deleted_at IS NULL`); a frozen dataclass `DriverVersionUsage(name, version, source_type, deployment_count)` and `list_usage() -> list[DriverVersionUsage]` to `ApplicationDriverVersionRepository` and its SQLModel class in `backend/styrmin_backend/repository/application_driver_version.py`: one row per driver version joined to `applicationdriver.name`, LEFT OUTER JOIN to `deployment` on `application_driver_version_id` with `deleted_at IS NULL` in the join condition, `COUNT(deployment.id)`, grouped by the driver version; it must not select `source_repository`, `source_branch`, `source_path`, `content_hash` or `source_commit_sha`
- [X] T011 [P] Tests `backend/tests/unit/repository/test_telemetry_counts.py` with the SQLite `session` fixture: an empty database gives zeros and an empty list; with one cluster, two environments, driver version A used by three deployments of which one is tombstoned (`deleted_at` set) and driver version B used by none, `count_live()` is 2 and `list_usage()` returns A with 2 and B with 0; an internal deployment (`internal=True`) is counted

### Payload builder (D2, D6, D9, [contracts/telemetry-report-wire-format.md](contracts/telemetry-report-wire-format.md))

- [X] T012 Create `backend/styrmin_backend/services/telemetry/payload.py`: `styrmin_version() -> str` reading `project.version` from `Path(styrmin_backend.__file__).resolve().parents[2] / "pyproject.toml"` with `tomllib`, accepted only when `project.name == "styrmin-mvp"`, else `"unknown"` (with one debug log line); `async build_report_data(uow: UnitOfWork) -> dict[str, Any]` that calls `uow.installation.get_or_create_install_id()`, the T010 queries, `platform.python_version()`, `platform.system()` and `platform.machine()`, merges `list_usage()` rows with equal `(name, version, source_type)` by adding their counts, sorts the entries by `name`, `version`, `source_type`, and returns a dict with exactly the FR-006 keys in contract order and each `drivers` entry with exactly `name`, `version`, `source_type`, `deployment_count`
- [X] T013 [P] Tests `backend/tests/unit/services/telemetry/test_payload.py` with a SQLite unit of work: the key list equals the FR-006 list in order; each driver entry has exactly the four keys; no value anywhere in the data contains the seeded repository URL, branch, path, cluster name, environment name or deployment name; two driver-version rows with the same name, version and source type but different `source_branch` become one entry with the summed count; entries are sorted; `deployment_count` equals the sum of the driver counts; `install_id` is the same on two calls; `styrmin_version()` returns the root `pyproject.toml` version in the repository and `"unknown"` when the path is patched to a missing file

**Checkpoint**: settings, install ID, counts and the report data exist and are tested

---

## Phase 3: User Story 1 - An install reports once a day (Priority: P1) 🎯 MVP

**Goal**: An install with default settings sends one report a day to the endpoint (FR-001, FR-002, FR-005, FR-006, FR-007, FR-012, FR-014, FR-015, FR-020)

**Independent Test**: With the endpoint pointed at the in-cluster sink, trigger the daily flow and confirm the sink receives one report with exactly the FR-006 keys, `kind: "styrmin"` and a valid checksum

### Sender (D3, D5, D8)

- [X] T014 [US1] Create `backend/styrmin_backend/services/telemetry/sender.py`: constants `ENVELOPE_KIND = "styrmin"`, `PAYLOAD_FORMAT = "1.0"`, `SEND_TIMEOUT_SECONDS = 10`; `checksum(data) -> str` as `hashlib.sha256(json.dumps(data).encode("utf-8")).hexdigest()`; `build_envelope(data) -> dict` returning `data`, `checksum`, `kind`, `payload_format` in that order; `async send_report(data, endpoint, logger) -> bool` that posts the envelope as JSON with `httpx.AsyncClient()` inside `asyncio.timeout(SEND_TIMEOUT_SECONDS)`, returns `True` for a 2xx response, and for any other status, `TimeoutError`, `httpx.HTTPError` or `OSError` logs one debug line with the error class or status code and returns `False`; it never raises
- [X] T015 [P] [US1] Tests `backend/tests/unit/services/telemetry/test_sender.py`, success path: against a local `ThreadingHTTPServer` on `127.0.0.1:0` (as `cli/tests/e2e/test_styrminctl_telemetry.py:67-120` does) a 200 response returns `True` and the server receives one POST with `Content-Type: application/json` and a body with keys `data`, `checksum`, `kind`, `payload_format`; `kind == "styrmin"` and `payload_format == "1.0"`; `checksum(data)` equals `styrminctl.telemetry.envelope.checksum(data)` for a fixed `data` dict built in FR-006 order

### Install ID on server start (D10, critique E2)

- [X] T016 [US1] Create `backend/styrmin_backend/services/telemetry/install.py` with `async ensure_install_id() -> UUID | None`: opens `get_unit_of_work()`, calls `uow.installation.get_or_create_install_id()`, commits, returns the ID; on any `Exception` logs one loguru warning (`"Could not create the telemetry install ID: {error}"`) and returns `None`. Call it in `app_initialization` in `backend/styrmin_backend/server/app.py` after `bootstrap_default_admin_from_settings()` and before `prefect_manager.initialize()`
- [X] T017 [P] [US1] Tests `backend/tests/unit/services/telemetry/test_install.py`: with `get_unit_of_work` patched to a SQLite unit of work, `ensure_install_id()` returns a UUID and a second call returns the same one; with `get_unit_of_work` patched to raise, it returns `None`, logs one warning and does not raise

### Daily flow and catalogue entry (D14, D16)

- [X] T018 [US1] Add `SEND_TELEMETRY_REPORT = "send_telemetry_report"` to `PrefectAction` in `backend/styrmin_backend/workflows/models.py`, and in `backend/styrmin_backend/workflows/catalogue.py` register, after the session cleanup entry, `LocalSourceWorkflowDefinition(name="send_telemetry_report", type=WorkflowType.INTERNAL, module="styrmin_backend.workflows.templates.telemetry", function="send_telemetry_report_flow", set_directory="/source/backend/", cron="43 2 * * *")` with a one-line comment citing spec 020
- [X] T019 [US1] Create `backend/styrmin_backend/workflows/templates/telemetry.py` with `@flow(name="send_telemetry_report") async def send_telemetry_report_flow() -> bool` and module constant `LATE_RUN_LIMIT = timedelta(hours=1)`. Order: `log = get_run_logger()`; read `config.SETTINGS.telemetry`; if `disabled_by()` is not `None`, log at debug and return `False`; if `now(UTC) - prefect.runtime.flow_run.scheduled_start_time > LATE_RUN_LIMIT`, log at debug and return `False`; build the data inside `async with get_unit_of_work() as uow` with `build_report_data(uow)` and `await uow.commit()`, and on any `Exception` log one warning and return `False` (critique E3); return `await send_report(data, settings.endpoint, log)`. The function must not raise, so the run always ends `Completed`
- [X] T020 [P] [US1] Tests `backend/tests/unit/workflows/test_telemetry_flow.py`, calling `send_telemetry_report_flow.fn()` with `get_run_logger`, `get_unit_of_work`, `build_report_data`, `send_report` and `prefect.runtime.flow_run.scheduled_start_time` patched in the module, as `backend/tests/unit/workflows/test_velero_backup_flow.py` does: with default settings and an on-time run, `send_report` is awaited once with the built data and the default endpoint; a run that starts 61 minutes late does not call `build_report_data` or `send_report`; a run 59 minutes late sends; and the catalogue entry `PrefectCatalogue().get_workflow_definition(PrefectAction.SEND_TELEMETRY_REPORT)` is INTERNAL and its `await to_deployment()` payload has one schedule with cron `"43 2 * * *"`

### Helm endpoint value and E2E sink (D11, D12, D13, FR-020)

- [X] T021 [US1] Add a `telemetry:` block under `styrmin:` in `helm/styrmin/values.yaml` with `endpoint: ""` and its `# --` comment ("Destination of the daily telemetry report. Leave empty for the OpsMill endpoint."), and in `helm/styrmin/templates/configmap.yaml` render `STYRMIN_TELEMETRY_ENDPOINT: {{ .Values.styrmin.telemetry.endpoint | quote }}` only inside `{{- if .Values.styrmin.telemetry.endpoint }}`, under a `# Telemetry` comment
- [X] T022 [P] [US1] Create the E2E sink in `backend/tests/e2e/fixtures/telemetry-sink/`: `sink.py` (standard library only: `ThreadingHTTPServer` on `0.0.0.0:8080`; `POST /report` stores the decoded JSON body in memory and answers 200; `GET /reports` answers the JSON list of stored bodies; `GET /healthz` answers 200), `Dockerfile` (`FROM python:3.14-slim`, copy `sink.py`, run it), and `deployment.yaml` (Deployment and ClusterIP Service `telemetry-sink` in namespace `default`, label `app=telemetry-sink`, port 8080, `imagePullPolicy: IfNotPresent`, image `telemetry-sink:latest`), following `backend/tests/e2e/fixtures/chart-server/`
- [X] T023 [US1] Add `styrmin.telemetry.endpoint: http://telemetry-sink.default.svc.cluster.local:8080/report` to `backend/tests/e2e/fixtures/styrmin-values.yaml` with a comment that points at the `telemetry_sink` fixture, and add a module-scoped fixture `telemetry_sink(vcluster)` to `backend/tests/e2e/conftest.py`, following `chart_server` (`conftest.py:376-428`): `docker build -t telemetry-sink:latest -f backend/tests/e2e/fixtures/telemetry-sink/Dockerfile backend/tests/e2e/fixtures/telemetry-sink`, create the Deployment and Service unless they already exist, `_wait_for_service_ready`, open `_portforward(service, remote_port=8080)`, `_wait_for_http(.../healthz)`, and yield the local base URL
- [X] T024 [US1] Create `backend/tests/e2e/test_server_telemetry.py` with `pytestmark = [pytest.mark.shard_general]` and one test `test_server_sends_daily_report` marked `@pytest.mark.ci` and `@pytest.mark.api_only(reason=...)` (no UI flow: it uses the Prefect API, the sink and `kubectl`), using `deployed_simple_app` and `telemetry_sink`. It reads the sink's report count, port-forwards to Service `prefect-server` in namespace `styrmin`, reads deployment `send_telemetry_report/send_telemetry_report` by name, calls `create_flow_run_from_deployment`, polls `read_flow_run` until final (as `backend/tests/e2e/test_worker_death_recovery.py:74-170` does), and asserts: the state is `COMPLETED`; the sink holds exactly one new report; its keys are `data`, `checksum`, `kind`, `payload_format`; `kind == "styrmin"`, `payload_format == "1.0"`; `checksum` equals `sha256(json.dumps(data))`; `list(data)` equals the FR-006 key list; `styrmin_version != "unknown"`; `cluster_count == 1`; `drivers` has an entry for the simple-app driver with `deployment_count >= 1`; no entry has keys other than the four driver keys

**Checkpoint**: the daily report is sent and received end to end (run in T046)

---

## Phase 4: User Story 2 - An operator turns telemetry off with one setting (Priority: P1)

**Goal**: `styrmin.telemetry.enabled: false`, `STYRMIN_TELEMETRY_ENABLED=false` and `DO_NOT_TRACK=1` each stop all requests (FR-003, FR-004)

**Independent Test**: Run the flow with each setting and confirm no HTTP request; render the chart with `styrmin.telemetry.enabled=false` and confirm the ConfigMap

- [X] T025 [P] [US2] Add flow tests to `backend/tests/unit/workflows/test_telemetry_flow.py`: with `STYRMIN_TELEMETRY_ENABLED=false`, and separately with `DO_NOT_TRACK=1`, `send_telemetry_report_flow.fn()` returns `False` and neither `build_report_data` nor `send_report` is called; also run one case with the real `send_report` against a local HTTP server and assert it received zero requests (FR-003)
- [X] T026 [US2] Add `enabled: true` with its `# --` comment ("Send one anonymous report a day to OpsMill. Set to false to turn telemetry off.") to the `styrmin.telemetry` block in `helm/styrmin/values.yaml`, and render `STYRMIN_TELEMETRY_ENABLED: {{ .Values.styrmin.telemetry.enabled | quote }}` in `helm/styrmin/templates/configmap.yaml` under the `# Telemetry` comment
- [X] T027 [US2] Helm template test `backend/tests/unit/test_helm_telemetry_values.py`: skip with a clear reason when `helm` is not on `PATH`; copy `helm/styrmin/Chart.yaml` without its `dependencies` key, `values.yaml`, `templates/_helpers.tpl`, `templates/configmap.yaml` and `templates/NOTES.txt` into `tmp_path` (the subcharts in `helm/styrmin/charts/` are not committed), run `helm template t <tmp chart> --show-only templates/configmap.yaml` and assert: by default `STYRMIN_TELEMETRY_ENABLED: "true"` and no `STYRMIN_TELEMETRY_ENDPOINT`; with `--set styrmin.telemetry.enabled=false` the value is `"false"`; with `--set styrmin.telemetry.endpoint=http://sink/report` the endpoint key is present with that value (FR-004, FR-020)

**Checkpoint**: every setting that turns telemetry off is tested

---

## Phase 5: User Story 3 - An operator views the exact report (Priority: P2)

**Goal**: `styrmin telemetry show` prints the data of the next report and sends nothing (FR-013, [contracts/cli-telemetry-show.md](contracts/cli-telemetry-show.md))

**Independent Test**: Run the command in the server pod, confirm the sink receives nothing, then run the flow and confirm the sink receives the same data

- [X] T028 [US3] Create `backend/styrmin_backend/cli/telemetry.py` with `telemetry_app = App(name="telemetry", help=...)` and command `show(config_file: Path | None = None)`: initialise settings as `cli/db.py` does (`initialize_and_exit` for validation errors), run `build_report_data` inside `get_unit_of_work()` and commit, print `json.dumps(data, indent=2)` to standard output with `print` (not Rich, so nothing is reformatted); on an exception print `Could not read the telemetry report: <error>` to standard error and exit with code 1. It must not import or call `send_report`. Register it in `backend/styrmin_backend/cli/app.py` as `app.command("styrmin_backend.cli.telemetry:telemetry_app", name="telemetry", help="Telemetry commands.")`
- [X] T029 [US3] Extend `test_server_sends_daily_report` in `backend/tests/e2e/test_server_telemetry.py`: before triggering the flow, find the server pod (`-l app.kubernetes.io/component=server,app.kubernetes.io/name=styrmin`), run `kubectl exec ... -c styrmin-server -- styrmin telemetry show` as `_kubectl_exec` in `backend/tests/e2e/test_driver_reload_identity.py:88-108` does, parse the JSON, and assert the sink's report count did not change after the command; after the flow run, assert the new report's `data` equals the parsed command output

**Checkpoint**: operators can view exactly what is sent

---

## Phase 6: User Story 4 - Telemetry does not cause failed flow runs or alerts (Priority: P2)

**Goal**: Endpoint failures end `Completed`, stop within 10 seconds and log at debug level only (FR-008, FR-009, SC-004)

**Independent Test**: Point the sender at an endpoint that refuses, hangs, or returns 4xx and 5xx, and confirm the outcome and the log level

- [X] T030 [P] [US4] Add failure tests to `backend/tests/unit/services/telemetry/test_sender.py`: a closed port (connection refused), an unresolvable host name, a local server that answers 404, and one that answers 503 each return `False` within 2 seconds and produce exactly one log call at debug level and none above it; a local server that accepts the connection and never answers returns `False` with `SEND_TIMEOUT_SECONDS` patched to 1, within 2 seconds (FR-009); `send_report` never raises
- [X] T031 [P] [US4] Add flow tests to `backend/tests/unit/workflows/test_telemetry_flow.py`: when `send_report` returns `False`, the flow returns `False` without raising and logs nothing above debug; when `build_report_data` raises, the flow returns `False`, logs one warning and does not raise (critique E3); when `send_report` is the real function and the endpoint refuses connections, `send_telemetry_report_flow.fn()` completes without raising (FR-008)

**Checkpoint**: an install without internet access sees no failed runs and no warnings from telemetry

---

## Phase 7: User Story 5 - The server log states whether telemetry is on (Priority: P3)

**Goal**: One INFO line on every server start, and the same information in the chart's install notes (FR-010, FR-017, critique P2)

**Independent Test**: Start the server with each setting and read the log; render the install notes

- [X] T032 [US5] Create `backend/styrmin_backend/services/telemetry/state.py` with `startup_message(settings: TelemetrySettings) -> str` returning exactly the two texts of [contracts/configuration.md](contracts/configuration.md) ("Startup log line"), with the effective endpoint in the "on" text and `disabled_by()` in the "off" text. In `backend/styrmin_backend/server/app.py` log `logger.info(startup_message(config.SETTINGS.telemetry))` right after the loguru logger is configured in `app_initialization` (D17)
- [X] T033 [P] [US5] Tests `backend/tests/unit/services/telemetry/test_state.py`: the "on" text names the endpoint, `styrmin telemetry show`, `STYRMIN_TELEMETRY_ENABLED=false`, `styrmin.telemetry.enabled=false` and `DO_NOT_TRACK=1`; with `STYRMIN_TELEMETRY_ENABLED=false` the text is `Telemetry is off (STYRMIN_TELEMETRY_ENABLED=false).`; with `DO_NOT_TRACK=1` it is `Telemetry is off (DO_NOT_TRACK=1).`; the result is one line (no newline)
- [X] T034 [US5] Add a telemetry section to `helm/styrmin/templates/NOTES.txt`: when `.Values.styrmin.telemetry.enabled` is true, say that Styrmin sends one anonymous report a day, that `helm upgrade ... --set styrmin.telemetry.enabled=false` turns it off, and that `kubectl exec` into the server pod with `styrmin telemetry show` prints the report; otherwise say telemetry is off. Add a case to `backend/tests/unit/test_helm_telemetry_values.py` that renders `templates/NOTES.txt` both ways and asserts the two texts
- [X] T035 [US5] Extend `test_server_sends_daily_report` in `backend/tests/e2e/test_server_telemetry.py`: read the server pod's log (`kubectl logs ... -c styrmin-server`) and assert it contains a line with `Telemetry is on` and the sink endpoint URL (critique E7)

**Checkpoint**: operators learn about telemetry from the log and the install notes

---

## Phase 8: User Story 6 - Test and development installs do not send reports to OpsMill (Priority: P3)

**Goal**: E2E, docker-compose, `invoke dev` and the local demo never reach the production endpoint (FR-011, D18)

**Independent Test**: Read each configuration and confirm a sink endpoint or telemetry off

- [X] T036 [P] [US6] Add `STYRMIN_TELEMETRY_ENABLED: "false"` to the `environment:` maps of the `server` and `task-worker` services in `docker-compose.yml`, with a one-line comment (`invoke dev` starts this file)
- [X] T037 [P] [US6] Add `styrmin.telemetry.enabled: false` with a one-line comment to `dev/local/demo-values.yaml`
- [X] T038 [US6] Add a unit test to `backend/tests/unit/test_helm_telemetry_values.py` that parses `docker-compose.yml`, `dev/local/demo-values.yaml` and `backend/tests/e2e/fixtures/styrmin-values.yaml` with `yaml.safe_load` and asserts: both compose services set `STYRMIN_TELEMETRY_ENABLED` to `"false"`; the demo values set `styrmin.telemetry.enabled` to `false`; the E2E values set `styrmin.telemetry.endpoint` to an `http://…svc.cluster.local` URL

**Checkpoint**: OpsMill's own installs are not counted

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Documentation (Constitution §VII), changelog, full checks and E2E evidence

- [ ] T039 [P] Update `docs/docs/reference/telemetry.md`: front-matter `title` and the first heading become "Telemetry & privacy" and the description covers both sources; keep the CLI content as a "CLI telemetry" section; add a "Server telemetry" section with: what is sent and why; a table of every FR-006 key and the four driver keys with an example; the statement that driver names are sent as written and that a custom driver name can identify the operator's organisation; what is never sent (FR-002 list); the schedule (once a day at 02:43 UTC, the first report at the first 02:43 UTC after the install starts, a missed run is not sent later); how to turn it off (`styrmin.telemetry.enabled: false`, `STYRMIN_TELEMETRY_ENABLED=false`, `DO_NOT_TRACK=1`) and that the setting must reach the server and the task worker, which the Helm value does; `styrmin telemetry show` with the `kubectl exec` example; the default endpoint and `styrmin.telemetry.endpoint` / `STYRMIN_TELEMETRY_ENDPOINT`; that the endpoint receives the install's public IP address as any HTTP server does and Styrmin does not add it to the report; that the server honours `HTTPS_PROXY`; the install ID and what happens when a database is restored elsewhere or rebuilt
- [ ] T040 [P] Update `helm/styrmin/README.md`: add `styrmin.telemetry.enabled` (default `true`) and `styrmin.telemetry.endpoint` (default `""`) to the "Styrmin Configuration" table, with a link to the documentation page
- [ ] T041 [P] Write `dev/adr/0061-server-anonymous-daily-telemetry.md` in the format of `dev/adr/0047-styrminctl-anonymous-fire-and-forget-telemetry.md` (Status Accepted, Date 2026-10-08, Source spec 020 and issue #274): context; decision (daily INTERNAL cron flow in the task worker, driver names sent as written, install ID stored in the single-row `installation` table, own checksum copy tested against `styrminctl`, version read from the root `pyproject.toml`, late runs skipped); consequences (the server side's new outbound request, `STYRMIN_WORKFLOW_ENABLE` does not stop it, the ingestion path must be confirmed before release)
- [ ] T042 [P] Update `CONTEXT.md`: extend the **Telemetry** entry so it covers both sources (the CLI's per-command event and the server's daily report, with the server's off settings and `styrmin telemetry show`), and add an **Install ID** entry (random UUID; for the CLI stored next to the token store, for the server stored in the `installation` table, one per database; _Avoid_: "instance ID", "customer ID")
- [ ] T043 [P] Update developer knowledge: `dev/knowledge/architecture.md` (one sentence that the task worker sends one report a day to the telemetry endpoint, link to ADR-0061); `dev/knowledge/backend/data-models.md` (the `installation` table); `dev/knowledge/backend/orchestration-flows.md` (a `SEND_TELEMETRY_REPORT` row in the workflow catalogue table and the `PrefectAction` list)
- [ ] T044 [P] Add the towncrier fragment `changelog/274.added.md` with `uv run towncrier create -c "..." 274.added.md`, describing in one or two sentences what operators get: a daily anonymous report, how to turn it off, and `styrmin telemetry show`
- [ ] T045 Run `uv run invoke format lint`, `uv run invoke test`, `uv run styrmin export graphql-schema schema.graphql && git diff --exit-code schema.graphql` (no change expected), and `cd docs && pnpm build`; fix every failure
- [ ] T046 Run `backend/tests/e2e/test_server_telemetry.py::test_server_sends_daily_report` with `-k api-chromium` under the E2E evidence rule above and record the evidence in `specs/020-backend-telemetry/e2e-evidence.md`
- [ ] T047 Walk through [quickstart.md](quickstart.md) sections 1 to 5 and correct any command or expected output that differs from the implementation

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies
- **Foundational (Phase 2)**: depends on Setup; blocks every user story
- **US1 (Phase 3)**: depends on Foundational
- **US2 (Phase 4)**: depends on US1 (T019 flow, T021 values block)
- **US3 (Phase 5)**: depends on Foundational; its E2E part (T029) depends on T024
- **US4 (Phase 6)**: depends on US1 (T014, T019)
- **US5 (Phase 7)**: depends on Foundational (T004); T034 depends on T026 and T027; T035 depends on T024
- **US6 (Phase 8)**: T036 and T037 have no dependency; T038 depends on T023, T026 and T027
- **Polish (Phase 9)**: depends on all stories; T046 depends on T024, T029 and T035

### Within each phase

- T006 before T007, T008; T008 before T009, T012; T010 before T011, T012; T012 before T013
- T014 before T015, T019; T016 before T017; T018 and T019 before T020; T021 before T023; T022 before T023; T023 before T024
- Edits to the same file run in task order: `helm/styrmin/values.yaml` and `configmap.yaml` (T021, T026); `test_telemetry_flow.py` (T020, T025, T031); `test_sender.py` (T015, T030); `test_helm_telemetry_values.py` (T027, T034, T038); `test_server_telemetry.py` (T024, T029, T035); `server/app.py` (T016, T032)

### Parallel Opportunities

- Phase 1: T002 and T003
- Phase 2: T005 with T006–T013; T007, T009, T011 and T013 once their code exists
- Phase 3: T015, T017, T020 and T022 in parallel after their code tasks
- Phase 8: T036 and T037
- Phase 9: T039 to T044

### Parallel Example: User Story 1

```text
After T014, T016, T019 are done:
  T015 sender tests          (backend/tests/unit/services/telemetry/test_sender.py)
  T017 install tests         (backend/tests/unit/services/telemetry/test_install.py)
  T020 flow and cron tests   (backend/tests/unit/workflows/test_telemetry_flow.py)
  T022 E2E sink fixture      (backend/tests/e2e/fixtures/telemetry-sink/)
```

---

## Implementation Strategy

### MVP first (User Stories 1 and 2)

1. Phases 1 and 2.
2. Phase 3 (US1): the report is built, sent once a day and received by the sink.
3. Phase 4 (US2): every off setting works. US1 and US2 are both P1 and ship together: a report that cannot be turned off must not be released.
4. Run T046 to validate end to end.

### Incremental delivery

1. US3: `styrmin telemetry show`.
2. US4: failure isolation tests.
3. US5: startup log line and install notes.
4. US6: development installs.
5. Phase 9: documentation, ADR, glossary, changelog, full checks, E2E evidence.

### Release prerequisite

Before the release, the owner of the ingestion endpoint confirms that `https://telemetry-endpoints.cloudflare-096.workers.dev/styrmin` accepts the envelope with `kind: "styrmin"` ([plan.md](plan.md)). This does not block any task.
