# Implementation Plan: Anonymous Daily Telemetry from the Styrmin Server

**Branch**: `fac/anonymous-telemetry-p5p4d` | **Date**: 2026-10-08 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/020-backend-telemetry/spec.md`, PRD [opsmill/styrmin#274 (comment)](https://github.com/opsmill/styrmin/issues/274#issuecomment-6069930520)

## Summary

OpsMill maintainers cannot count Styrmin installs per version or per driver. This plan makes the server send one anonymous report a day, which operators can view with `styrmin telemetry show` and turn off with one setting.

The approach, from [research.md](research.md):

- A new INTERNAL Prefect flow, `send_telemetry_report`, runs on the cron `43 2 * * *` (UTC) from the workflow catalogue, like the session cleanup flow (D16). Prefect's idempotent registration gives one run a day whatever the number of restarts or replicas. The flow skips runs that start more than an hour late, so a missed report is not sent later (D14).
- The flow runs in the task worker, so the settings reach it through the shared Helm ConfigMap. Two new Helm values set them: `styrmin.telemetry.enabled` and `styrmin.telemetry.endpoint` (D11).
- A payload builder in `services/telemetry/` reads the counts and driver usage through new repository queries, and is shared by the flow and the CLI command (D1, D2, D9).
- The sender wraps the data in the `styrminctl` envelope with `kind: "styrmin"` and `payload_format: "1.0"`, using its own copy of the checksum that a test checks against `styrminctl` (D3, D5). Each send stops after 10 seconds in total and failures are logged at debug level (D8).
- The install ID is a single row in a new `installation` table, created on server start with an insert that two replicas can run at the same time (D10).
- The Styrmin version is read from the root `pyproject.toml` that the release workflow bumps, because no installed package carries it (D6).
- The E2E test reuses the Styrmin install and the simple-app deployment of `shard_general` and sends to a sink inside the vcluster (D12, D13, D19).

## Technical Context

**Language/Version**: Python 3.14+ (backend, backend CLI); Helm chart templates.

**Primary Dependencies**: Prefect 3.8.6 (cron deployment, `get_run_logger`, `prefect.runtime`), pydantic-settings, SQLModel and SQLAlchemy (async), Alembic, httpx (already used by the backend), Cyclopts, loguru. No new dependency.

**Storage**: PostgreSQL (SQLite in unit tests). One Alembic revision: new table `installation` ([data-model.md](data-model.md)).

**Testing**: pytest unit tests (SQLite and the existing PostgreSQL container fixture), `helm template` for the ConfigMap, one `api_only` E2E test on the vcluster.

**Target Platform**: Linux containers on Kubernetes (Helm chart) and docker-compose for development.

**Project Type**: Web service (server and task worker) with a server management CLI.

**Performance Goals**: One HTTP request a day per install. The report needs four aggregate queries; the number of rows they return grows with the number of driver versions, not with the number of deployments.

**Constraints**: Each send stops after 10 seconds (FR-009). The flow never ends in a failed state (FR-008). No log entry above debug for a failed send (SC-004). No change to the GraphQL schema, the frontend, the SDK or `styrminctl`.

**Scale/Scope**: One cluster per install (ADR-039), tens of environments, hundreds of deployments, tens of driver versions.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | How the plan meets it |
|---|---|---|
| I. Declarative reconciliation | Not affected | The flow reads state and changes nothing in clusters. |
| II. Driver-based deployment | Not affected | Driver versions are read only. |
| III. Layered architecture | Pass | Flow and CLI → `services/telemetry` → repositories → database. Counts are new repository methods (D1). |
| IV. Typed errors | Pass | No new error class. The sender catches send failures and returns `False`; the flow catches the rest and logs at debug level (D8). No GraphQL change, so no `ServiceError` is needed. |
| V. Tests | Pass | Unit tests for every module marked "Yes" in the PRD table; one `api_only` E2E test that reuses `deployed_simple_app` in `shard_general` (D19). Turning telemetry off is covered by unit tests only; the PRD records that this was confirmed on 2026-10-08. No GraphQL propagation test, because the schema does not change. |
| VI. Format and lint | Pass | `uv run invoke format lint` before each commit. |
| VII. Documentation | Pass | Tasks update `docs/docs/reference/telemetry.md`, `helm/styrmin/README.md`, a new ADR, `CONTEXT.md`, `dev/knowledge/backend/data-models.md`, `dev/knowledge/backend/orchestration-flows.md`, and add a towncrier fragment. |

Governance gates:

| Gate | Crossed | Note |
|---|---|---|
| Database schema or migration | Yes | One table. The PRD records approval on 2026-10-08. |
| GraphQL schema | No | |
| New dependency | No | `httpx`, `tomllib` (standard library) and Prefect are already used. |
| CI/CD workflow | No | The E2E test goes into the existing `shard_general`. The version is read without changing the release workflow (D6). |
| Authentication or authorization | No | `styrmin telemetry show` runs in the server pod; access to the cluster controls who runs it. |

Result: pass. Re-checked after Phase 1 design: still pass. The Helm value `styrmin.telemetry.endpoint` is an addition to the PRD's single Helm value, needed for FR-011 (D11); it changes no gate.

## Project Structure

### Documentation (this feature)

```text
specs/020-backend-telemetry/
├── spec.md
├── plan.md                 # This file
├── research.md             # Decisions D1–D19
├── data-model.md           # installation table, queries, report data
├── quickstart.md           # Validation guide
├── contracts/
│   ├── telemetry-report-wire-format.md
│   ├── cli-telemetry-show.md
│   └── configuration.md
├── checklists/
│   └── requirements.md
└── tasks.md                # Created by /speckit-tasks
```

### Source Code (repository root)

```text
backend/styrmin_backend/
├── config.py                               # + TelemetrySettings, Settings.telemetry, SETTINGS.telemetry
├── db/
│   ├── models.py                           # + Installation
│   └── migrations/versions/<rev>_add_installation.py   # new
├── repository/
│   ├── installation.py                     # new: get_or_create_install_id()
│   ├── cluster.py                          # + count()
│   ├── environment.py                      # + count()
│   ├── deployment.py                       # + count_live()
│   └── application_driver_version.py      # + list_usage(), DriverVersionUsage
├── services/
│   ├── unit_of_work.py                     # + installation repository
│   └── telemetry/                          # new package
│       ├── __init__.py
│       ├── payload.py                      # build_report_data(uow), styrmin_version()
│       ├── sender.py                       # checksum(), build_envelope(), send_report()
│       └── state.py                        # startup_message(settings)
├── workflows/
│   ├── models.py                           # + PrefectAction.SEND_TELEMETRY_REPORT
│   ├── catalogue.py                        # + INTERNAL cron entry "43 2 * * *"
│   └── templates/telemetry.py              # new: send_telemetry_report_flow
├── server/app.py                           # + startup log line, + get_or_create_install_id()
└── cli/
    ├── app.py                              # + "telemetry" command group
    └── telemetry.py                        # new: show

backend/tests/
├── unit/
│   ├── test_telemetry_settings.py
│   ├── test_helm_telemetry_values.py
│   ├── db/test_installation_migration.py
│   ├── repository/test_installation_repository.py
│   ├── repository/test_telemetry_counts.py
│   ├── services/telemetry/test_payload.py
│   ├── services/telemetry/test_sender.py
│   ├── services/telemetry/test_state.py
│   └── workflows/test_telemetry_flow.py    # flow behaviour and catalogue cron
└── e2e/
    ├── conftest.py                         # + telemetry_sink fixture
    ├── fixtures/styrmin-values.yaml        # + styrmin.telemetry.endpoint
    ├── fixtures/telemetry-sink/            # new: Dockerfile, sink.py, deployment.yaml
    └── test_server_telemetry.py            # new, api_only, ci, shard_general

helm/styrmin/
├── values.yaml                             # + styrmin.telemetry.{enabled,endpoint}
├── templates/configmap.yaml                # + STYRMIN_TELEMETRY_ENABLED, STYRMIN_TELEMETRY_ENDPOINT
└── README.md                               # + both values

docker-compose.yml                          # + STYRMIN_TELEMETRY_ENABLED on server and task-worker
dev/local/demo-values.yaml                  # + styrmin.telemetry.enabled: false
docs/docs/reference/telemetry.md            # renamed title, + server section
dev/adr/0061-server-anonymous-daily-telemetry.md   # new
dev/knowledge/backend/data-models.md        # + installation table
dev/knowledge/backend/orchestration-flows.md        # + send_telemetry_report in the catalogue table
CONTEXT.md                                  # Telemetry entry extended, Install ID added
changelog/274.added.md                      # towncrier fragment
```

**Structure Decision**: The feature lives in the existing backend package and Helm chart. No new workspace member, no frontend or SDK change.

## Implementation Order

1. Settings and effective state (D7) with unit tests. Nothing else depends on the database.
2. `installation` model, Alembic revision, repository and the startup call (D10), with the migration and repository tests.
3. Repository count and usage queries, then the payload builder (D2, D6, D9), with tests.
4. Sender (D3, D8) with tests, including the checksum check against `styrminctl`.
5. Flow, catalogue entry and the late-run guard (D14, D16), with tests.
6. Startup log line (D17) and `styrmin telemetry show`.
7. Helm values and ConfigMap (D11), docker-compose and demo values (D18), Helm template test.
8. E2E sink fixture, values overlay and `test_server_telemetry.py` (D12, D13, D19), run to a pass with evidence.
9. Documentation, ADR, `CONTEXT.md`, knowledge pages and the changelog fragment.

## Risks

| Risk | Effect | Mitigation |
|---|---|---|
| The ingestion endpoint does not accept `/styrmin` or `kind: "styrmin"` | Reports are refused; the install sees nothing, by design | Release prerequisite below. The URL is one constant. |
| The root `pyproject.toml` is not in a future image layout | `styrmin_version` becomes `"unknown"` | A unit test asserts the version is read in the repository; the E2E test asserts it is not `"unknown"` in the image. |
| A scheduled run fires during an E2E session | An extra report reaches the sink | The test counts reports before and after its own run. |
| Prefect deletes and recreates future scheduled runs on every server start | None for telemetry; the run of the day is recreated with the same idempotency key | Documented in research, no action. |

## Release prerequisite

The owner of the ingestion endpoint confirms that `https://telemetry-endpoints.cloudflare-096.workers.dev/styrmin` accepts the envelope with `kind: "styrmin"` (spec FR-015, research D4). This does not block implementation or the E2E test, which uses its own sink.

## Complexity Tracking

No constitution violation to justify.
