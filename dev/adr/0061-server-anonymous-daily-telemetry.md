# ADR-061: Anonymous daily telemetry report from the Styrmin server

**Status**: Accepted
**Date**: 2026-10-08
**Source**: feature — `specs/020-backend-telemetry/` (research.md D1–D19, data-model.md, contracts/);
PRD and seed issue [#274](https://github.com/opsmill/styrmin/issues/274)
**Related**: [ADR-047](0047-styrminctl-anonymous-fire-and-forget-telemetry.md) (the `styrminctl`
event whose envelope and checksum this report reuses), [ADR-001](0001-alembic-database-migrations.md)
(the revision that adds the `installation` table), [ADR-008](0008-deployment-soft-delete-tombstoning.md)
(tombstoned deployments are not counted), [ADR-016](0016-authentication-and-sessions.md) (the daily
session cleanup flow, the pattern the report follows)

## Context

OpsMill maintainers had no data on how many Styrmin installs run, which Styrmin
versions they run, or which application drivers they use. Decisions about how
long to support a version and which drivers to work on were made without data.
`styrminctl` already sends anonymous telemetry (ADR-047), but it reports CLI
commands only, from the operator's workstation, and says nothing about the
installs themselves.

The report has to come from the install, so it has to come from the server side.
Until now, the server side sent no data about the install to OpsMill. A report
from the server side has to meet the same constraints as the CLI event: it
must not degrade the install, it must not carry the names of clusters,
environments or deployments, repository addresses or credentials, and one
setting must turn it off.

Five facts of the existing code shaped the design:

- INTERNAL flows run in the task worker (`styrmin-work-pool`), not in the server
  process. The server and the task worker both load the shared ConfigMap.
- Catalogue registration is idempotent, and Prefect gives each scheduled flow
  run to one worker, so server restarts and extra replicas do not create extra
  runs.
- A run that is due while the task worker is down still runs when the worker
  comes back, because Prefect keeps `Late` runs in the `SCHEDULED` state type.
- No running code knew the Styrmin release version: the release workflow bumps
  only the workspace root `pyproject.toml`, which is never installed as a
  package, and `styrmin-backend` stays at `0.1.0`.
- No code reads `STYRMIN_WORKFLOW_ENABLE`, although `config.py` declares it and
  the chart renders it.

## Decision

The server side sends one anonymous report a day, built from counts in the
database, inside the `styrminctl` envelope with `kind: "styrmin"`.

- **A daily INTERNAL cron flow in the task worker.** The catalogue entry
  `PrefectAction.SEND_TELEMETRY_REPORT` registers the flow
  `send_telemetry_report` (`workflows/templates/telemetry.py`) as an INTERNAL
  flow with the cron `43 2 * * *`, which Prefect reads as UTC. It is scheduled
  in the same way as the daily session cleanup flow, so the rule "at most one
  report a day" needs no extra code. The flow reads the telemetry settings when
  it runs, builds the report data, and posts it once. The post stops after 10 seconds in total
  (`asyncio.timeout` around the `httpx` request). A send failure is logged at
  debug level; a failure to build the report is logged at warning level. The
  flow never raises, so its run always ends `Completed`.
- **Late runs are skipped.** A run that starts more than one hour after its
  scheduled time logs at debug level and sends nothing. Without this check, a
  report missed while the task worker was down would be sent when the worker
  comes back. Prefect has no setting that drops runs that are too late. A run
  started by hand has its start time as its scheduled time, so it sends.
- **Driver names are sent as written.** Each `drivers` entry has exactly
  `name`, `version`, `source_type` and `deployment_count`. Which drivers installs
  use is one of the two questions the reports must answer (PRD, "Differences
  from issue #274"). A custom driver name can identify the operator's
  organisation; the documentation page states this. The driver source
  repository URL, branch, path and provenance fingerprint are never read by the
  query. Driver versions that differ only in those fields are merged into one
  entry with their counts added, and the entries are sorted, so the same
  database state gives the same data and checksum.
- **The install ID is stored in the single-row `installation` table.** One
  install is one Styrmin database. The table has an integer primary key with
  `CHECK (id = 1)`, so a second row cannot exist. The repository inserts
  `(1, uuid4())` with `ON CONFLICT (id) DO NOTHING` and then selects the row, so
  two replicas that start at the same time agree on one ID without a lock. The
  server creates the ID on every start, whether telemetry is on or off, so the ID
  does not change when an operator turns telemetry on later. A failure to
  create it logs one warning and does not stop the server.
- **The server has its own copy of the checksum.** `services/telemetry/sender.py`
  computes `sha256(json.dumps(data))` and builds the envelope itself, instead of
  importing `styrminctl.telemetry.envelope`. The server does not depend on its
  own client for 15 lines of code. A unit test asserts that both functions give
  the same digest for the same data, so the ingestion endpoint can verify both
  kinds of report with one function.
- **The Styrmin version is read from the root `pyproject.toml`.** The report
  reads `project.version` from the workspace root `pyproject.toml`, which the
  Docker image copies to `/source/pyproject.toml`, and accepts it only when
  `project.name` is `styrmin-mvp`. Otherwise it reports `unknown`. Passing the
  chart version or the image tag from Helm was rejected, because an operator who
  sets `image.tag` would report the wrong version, and docker-compose has no
  chart.
- **Three settings turn it off; one value changes the destination.**
  `STYRMIN_TELEMETRY_ENABLED=false` (Helm value `styrmin.telemetry.enabled`) or
  `DO_NOT_TRACK=1` turns telemetry off. `STYRMIN_TELEMETRY_ENDPOINT` (Helm value
  `styrmin.telemetry.endpoint`) changes the destination; the chart renders it only
  when it is not empty. The server logs one INFO line on every start that says
  whether telemetry is on, and `styrmin telemetry show` prints the report data
  without sending it.

## Consequences

- **A new outbound request from the server side.** Every install with default
  settings sends the report in one HTTPS request a day to
  `https://telemetry.opsmill.cloud/styrmin`. The request
  leaves from the task worker, not the server pod. Network policies or proxies
  that operators configure have to account for it, or operators turn telemetry
  off. The task worker honours `HTTPS_PROXY` and `NO_PROXY`, but the chart has
  no value that sets them.
- **The off setting must reach two processes.** The server logs whether
  telemetry is on; the task worker decides whether to send. The Helm value and
  the ConfigMap reach both. An operator who sets `STYRMIN_TELEMETRY_ENABLED` or
  `DO_NOT_TRACK` on one container only can see "Telemetry is off" in the server
  log while the task worker still sends reports.
- **`STYRMIN_WORKFLOW_ENABLE` does not stop the report.** No code reads the
  setting, so it does not stop this flow or any other. The telemetry flow does
  not read it either, because giving the setting a meaning for one flow only
  would be misleading. Fixing the setting for all workflows is separate work.
- **A database change.** The Alembic revision `3b926acd0791` adds the
  `installation` table. A dump restored into a second install reports the same
  install ID as the original; a database rebuilt from scratch reports a new one.
- **Development installs do not report.** `docker-compose.yml` and
  `dev/local/demo-values.yaml` turn telemetry off. The E2E suite sends reports to
  an in-cluster sink (`backend/tests/e2e/fixtures/telemetry-sink/`).
- **Reports can be lost.** Each run sends one request with no retry and no
  queue. An install that is down at 02:43 UTC, or that is deleted before its
  first run, is not counted that day.
- **The ingestion path must be confirmed before the release.** It is not known
  whether the ingestion endpoint accepts the `/styrmin` path and
  `kind: "styrmin"`. The owner of the endpoint must confirm it before the release
  that ships this feature. Until then, a refused report is a debug-level
  failure that the install does not show.

## Alternatives Considered

- **Store the install ID in a file or a Kubernetes Secret.** Rejected: the PRD
  defines one install as one Styrmin database, and a file or Secret would not
  follow a database restore or rebuild.
- **A UUID primary key that is the install ID.** Rejected: it cannot stop a
  second row from being inserted.
- **Import the envelope from `styrminctl`, or move it to `styrmin-sdk`.**
  Rejected: the first reverses the dependency between server and client; the
  second puts non-GraphQL code in the GraphQL client SDK.
- **One entry per driver version row.** Rejected: rows that differ only in the
  fields the report leaves out would look like duplicates to the endpoint.
- **A send minute derived from the install ID, to spread the load.** Rejected
  for the first version: the catalogue is built before the database is read, so
  the cron would have to be computed at registration time.
