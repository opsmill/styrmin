# Feature Specification: Anonymous Daily Telemetry from the Styrmin Server

**Feature Branch**: `fac/anonymous-telemetry-p5p4d`

**Created**: 2026-10-08

**Status**: Draft

**Input**: PRD "Anonymous daily telemetry from the Styrmin backend" — [opsmill/styrmin#274 (comment)](https://github.com/opsmill/styrmin/issues/274#issuecomment-6069930520). Seed issue: [#274](https://github.com/opsmill/styrmin/issues/274). The PRD is the source of truth, including its section "Differences from issue #274".

## Context

OpsMill maintainers have no data on how many Styrmin installs are running, which Styrmin versions they run, or which **application drivers** they use ([#274](https://github.com/opsmill/styrmin/issues/274)). So decisions about how long to support a version, and which drivers to invest in, are made without data. `styrminctl` already sends anonymous **telemetry** ([ADR-047](../../dev/adr/0047-styrminctl-anonymous-fire-and-forget-telemetry.md)), but it reports CLI commands only and says nothing about the installs themselves.

With this feature, the **server** (called "the backend" in the PRD) sends one anonymous report a day to an OpsMill endpoint. The report contains a random install ID, the Styrmin, Python and operating system versions, the number of **clusters**, **environments** and live **deployments**, and every loaded **application driver version** with the number of live deployments that use it. Telemetry is on by default. An operator turns it off with one Helm value, with `STYRMIN_TELEMETRY_ENABLED=false`, or with `DO_NOT_TRACK=1`, and views the exact report with `styrmin telemetry show` in the server pod.

Driver names are sent exactly as the operator named them, because driver usage is one of the two questions the reports must answer. A custom driver name can identify the operator's organisation, and the documentation states this ([PRD, "Differences from issue #274"](https://github.com/opsmill/styrmin/issues/274#issuecomment-6069930520)).

## User Scenarios & Testing *(mandatory)*

The actors are:

- the **OpsMill maintainer**, who reads the received reports to make support and roadmap decisions
- the **operator**, who installs and runs Styrmin and decides whether reports leave the install
- the **Styrmin developer**, whose test and development installs must not be counted

### User Story 1 - An install reports once a day (Priority: P1)

An install with default settings sends one report a day to the OpsMill endpoint. From the received reports, a maintainer counts the installs that reported in the last 7 days for each Styrmin version, finds which drivers and driver versions installs have loaded and how many live deployments use each one, and finds how many clusters, environments and live deployments each install has.

**Why this priority**: Counting installs per Styrmin version and per driver version is the reason for the feature (PRD user stories 1, 2 and 3; SC-005).

**Independent Test**: Install Styrmin with the endpoint pointed at a local sink. Load one driver version that no deployment uses and one that several deployments use, one of them tombstoned. Run the daily telemetry flow and confirm the sink receives one report that contains exactly the keys in FR-006, the expected counts, and both driver versions with the expected deployment counts.

**Acceptance Scenarios**:

1. **Given** an operator installed Styrmin with the Helm chart's default values, **When** the daily telemetry flow runs, **Then** the endpoint receives exactly one report that contains the keys listed in FR-006.
2. **Given** an install has one driver version that no deployment uses, **When** the daily telemetry flow runs, **Then** the report lists that driver version with a deployment count of 0.
3. **Given** an install has a driver version used by three deployments, one of them tombstoned, **When** the daily telemetry flow runs, **Then** the report lists that driver version with a deployment count of 2, and `deployment_count` does not count the tombstoned deployment.
4. **Given** the server restarted several times during a day, or runs with more than one replica, **When** the day ends, **Then** the endpoint received at most one report from the install for that day.
5. **Given** the server restarted, **When** the next daily report is sent, **Then** it carries the same install ID as the report before the restart.

---

### User Story 2 - An operator turns telemetry off with one setting (Priority: P1)

An operator who does not want reports to leave the install turns telemetry off with the Helm value `styrmin.telemetry.enabled: false`, with the environment variable `STYRMIN_TELEMETRY_ENABLED=false`, or with `DO_NOT_TRACK=1`, the setting they already use for other tools. After that, the install sends nothing.

**Why this priority**: Telemetry is on by default, so a reliable way to turn it off is part of the minimum the feature must deliver (PRD user stories 4 and 5; P1 journey).

**Independent Test**: Run the daily telemetry flow once with each setting that turns telemetry off and confirm that no request reaches the endpoint. Render the Helm chart with `styrmin.telemetry.enabled: false` and confirm the server environment contains `STYRMIN_TELEMETRY_ENABLED=false`.

**Acceptance Scenarios**:

1. **Given** an operator set `styrmin.telemetry.enabled: false` in the Helm values, **When** the daily telemetry flow runs, **Then** the server sends no request.
2. **Given** an operator set `STYRMIN_TELEMETRY_ENABLED=false`, **When** the daily telemetry flow runs, **Then** the server sends no request.
3. **Given** an operator set `DO_NOT_TRACK=1`, **When** the daily telemetry flow runs, **Then** the server sends no request.

---

### User Story 3 - An operator views the exact report (Priority: P2)

An operator who wants to check what leaves the install runs `styrmin telemetry show` in the server pod and views the data that the next report will contain. The command sends nothing.

**Why this priority**: Viewing the exact report lets the operator decide with facts whether to keep telemetry on (PRD user story 6; P2 journey).

**Independent Test**: Point the endpoint at a local sink, run `styrmin telemetry show` and confirm the sink receives nothing. Then run the daily telemetry flow and confirm the sink receives the same data that the command printed.

**Acceptance Scenarios**:

1. **Given** an operator wants to check what is sent, **When** they run `styrmin telemetry show` in the server pod, **Then** the command prints the data the next report would contain and sends nothing.
2. **Given** an operator ran `styrmin telemetry show` and nothing in the install changed afterwards, **When** the daily telemetry flow runs, **Then** the data the endpoint receives is the same as the data the command printed.
3. **Given** telemetry is turned off, **When** an operator runs `styrmin telemetry show`, **Then** the command prints the data a report would contain, so the operator can check it before turning telemetry on. [CLAUDE RECOMMENDED – based on PRD user story 6, which asks to view the payload without conditions, and on the PRD's statement that the command never sends anything]

---

### User Story 4 - Telemetry does not cause failed flow runs or alerts (Priority: P2)

An operator runs Styrmin where the server cannot reach the internet, or where outbound traffic is blocked. The daily telemetry flow fails to send its report every day, but no flow run fails and no log entry above debug level appears, so telemetry does not trigger the operator's alerts.

**Why this priority**: Many installs run without internet access. Failed flow runs or warnings every day would make operators turn telemetry off or report bugs (PRD user story 8; SC-004).

**Independent Test**: Point the endpoint at an address that refuses connections, at one that never responds, and at one that returns a 4xx and a 5xx status. For each, run the daily telemetry flow and confirm the flow run ends `Completed`, the send attempt stops within 10 seconds, and the failure is logged at debug level only.

**Acceptance Scenarios**:

1. **Given** the endpoint refuses the connection, **When** the daily telemetry flow runs, **Then** the flow run ends `Completed` and the failure is logged at debug level.
2. **Given** the endpoint accepts the connection but never responds, **When** the daily telemetry flow runs, **Then** the send attempt stops after 10 seconds and the flow run ends `Completed`.
3. **Given** the endpoint returns a 4xx or 5xx status, **When** the daily telemetry flow runs, **Then** the flow run ends `Completed` and the failure is logged at debug level.

---

### User Story 5 - The server log states whether telemetry is on (Priority: P3)

An operator reads the server log they already read and finds, on every start, whether telemetry is on or off. When it is on, the line says how to turn it off and how to view the report. When it is off, the line names the setting that turned it off.

**Why this priority**: The log line is how operators who do not read the documentation learn that telemetry exists (PRD user story 7). The feature works without it, so it ranks below the stories above.

**Independent Test**: Start the server once with default settings, once with `STYRMIN_TELEMETRY_ENABLED=false` and once with `DO_NOT_TRACK=1`, and confirm one INFO line each time with the expected content.

**Acceptance Scenarios**:

1. **Given** telemetry is on, **When** the server starts, **Then** the log contains one INFO line that says telemetry is on, how to turn it off, and how to view the report with `styrmin telemetry show`.
2. **Given** `DO_NOT_TRACK=1` is set, **When** the server starts, **Then** the log contains one INFO line that says telemetry is off and names `DO_NOT_TRACK` as the setting that turned it off.
3. **Given** the server already started before, **When** it starts again, **Then** the line is logged again.

---

### User Story 6 - Test and development installs do not send reports to OpsMill (Priority: P3)

A Styrmin developer runs E2E tests, docker-compose or `invoke dev`. These installs never send reports to the production endpoint, so OpsMill's own test installs are not counted.

**Why this priority**: Reports from test installs would distort the counts maintainers rely on (PRD user story 9). It affects data quality, not what operators view.

**Independent Test**: Read the E2E fixtures, the docker-compose files and the `invoke dev` settings, and confirm each one points the endpoint at a local sink or turns telemetry off.

**Acceptance Scenarios**:

1. **Given** an E2E session starts a Styrmin install, **When** the daily telemetry flow runs, **Then** the report goes to the local sink of the E2E session, not to the production endpoint.
2. **Given** a developer starts docker-compose or `invoke dev`, **When** the daily telemetry flow runs, **Then** no report reaches the production endpoint.

---

### Edge Cases

- The endpoint cannot be reached because the install has no internet access or outbound traffic is blocked: the flow run ends `Completed` and the failure is logged at debug level, every day.
- The endpoint never responds: the send attempt stops after 10 seconds.
- The install is down at the scheduled time: no report is sent that day, and the missed report is not sent later. This also holds when only the process that runs the daily flow is down: a run that starts more than one hour after its scheduled time sends nothing ([research D14](research.md)).
- A database dump is restored into a second install: both installs report the same install ID.
- The database is rebuilt from scratch: the install reports a new install ID.
- An operator sets `STYRMIN_WORKFLOW_ENABLE=false`: the PRD says the daily flow then does not run. In the current code no part of Styrmin reads this setting, so it does not stop the daily flow or the report ([research D15](research.md)). Operators turn telemetry off with the settings in FR-003 and FR-004. This feature does not change `STYRMIN_WORKFLOW_ENABLE`.
- No cluster has been added: the report contains `cluster_count: 0`. [ADR-039](../../dev/adr/0039-single-cluster-platform-scope.md) limits an install to one cluster, so the value is 0 or 1.
- Both `STYRMIN_TELEMETRY_ENABLED=false` and `DO_NOT_TRACK=1` are set: telemetry is off. Any one setting that turns telemetry off is enough.
- `DO_NOT_TRACK` is set to a value other than `1`, such as `true`: it does not turn telemetry off, as in `styrminctl` ([eligibility.py](../../cli/src/styrminctl/telemetry/eligibility.py)).
- An environment has the internal ingress controller deployment that Styrmin creates for it: that deployment is counted like any other live deployment, and the internal driver version it uses appears in `drivers`. [CLAUDE RECOMMENDED – based on PRD FR-001 and FR-006, which count all live deployments without exceptions, and on `services/deployment.py`, where the ingress controller is a deployment with a driver version]
- A driver version was loaded but no deployment uses it: it appears in `drivers` with a deployment count of 0.

## Requirements *(mandatory)*

### Functional Requirements

The numbers FR-001 to FR-013 are the same as in the PRD. FR-014 onwards add requirements that the PRD states outside its list of functional requirements, and FR-020, which the plan needs for FR-011.

Report content:

- **FR-001**: Each report MUST list every loaded application driver version, including versions that no deployment uses. Each entry contains:
  - the driver name, exactly as the operator named it
  - the driver version
  - the source type (`git` or `local`)
  - the number of live deployments that use it, not counting tombstoned deployments ([ADR-008](../../dev/adr/0008-deployment-soft-delete-tombstoning.md))
- **FR-002**: Reports MUST NOT contain the driver source repository URL, branch or path.
- **FR-006**: The report data MUST contain only these keys:
  - `install_id`
  - `styrmin_version`, `python_version`, `os_family`, `arch`
  - `cluster_count`, `environment_count`, `deployment_count` (live deployments only)
  - `drivers`
- **FR-007**: The report MUST use the `styrminctl` envelope (`data`, `checksum`, `kind`, `payload_format`) with `kind: "styrmin"` ([wire format](../archive/015-styrminctl-telemetry/contracts/telemetry-wire-format.md)). The checksum MUST be computed the same way as for `styrminctl` reports, so the ingestion endpoint can verify it.

Turning telemetry off and changing the destination:

- **FR-003**: The server MUST send no request when `STYRMIN_TELEMETRY_ENABLED=false` or `DO_NOT_TRACK=1` is set.
- **FR-004**: Operators MUST be able to turn telemetry off with the Helm value `styrmin.telemetry.enabled: false`, which sets `STYRMIN_TELEMETRY_ENABLED` in the server environment.
- **FR-005**: Operators MUST be able to change the destination with `STYRMIN_TELEMETRY_ENDPOINT`.
- **FR-020**: Operators MUST be able to set `STYRMIN_TELEMETRY_ENDPOINT` with the Helm value `styrmin.telemetry.endpoint`. When the value is empty, the chart does not set the variable. [CLAUDE RECOMMENDED – based on FR-011, which needs the E2E install to send to a local sink, and on the chart, which has no field for other environment variables ([values.yaml](../../helm/styrmin/values.yaml))]
- **FR-015**: When `STYRMIN_TELEMETRY_ENDPOINT` is not set, reports MUST go to the OpsMill endpoint `https://telemetry-endpoints.cloudflare-096.workers.dev/styrmin`. [CLAUDE RECOMMENDED – based on the `styrminctl` default endpoint `https://telemetry-endpoints.cloudflare-096.workers.dev/styrminctl` in `cli/src/styrminctl/telemetry/config.py`, which uses one path per reporting product. The PRD leaves the URL open. The owner of the ingestion endpoint must confirm the path accepts `kind: "styrmin"` before the release.]

Sending:

- **FR-008**: The daily telemetry flow MUST end in the `Completed` state when the endpoint refuses the connection, does not respond, or returns a 4xx or 5xx status. A failed send MUST be logged at debug level only.
- **FR-009**: Each send attempt MUST stop after 10 seconds.
- **FR-012**: The server MUST send at most one report a day, at a fixed time of day, from a scheduled flow in the same way as the daily session cleanup flow ([ADR-016](../../dev/adr/0016-authentication-and-sessions.md)). Restarts of the server and extra server replicas MUST NOT cause extra reports.
- **FR-014**: The install ID MUST be a random UUID that is created the first time the server starts and stored in the Styrmin database. Every later report from the same database MUST carry the same install ID, across restarts and server replicas. The install ID MUST be created whether telemetry is on or off, so that it does not change when an operator turns telemetry on later.

Viewing the report and the startup log line:

- **FR-010**: On every start, the server MUST log one line at INFO level that says whether telemetry is on or off. When it is on, the line says how to turn it off and how to view the report. When it is off, the line names the setting that turned it off.
- **FR-013**: Operators MUST be able to print the data of the next report with `styrmin telemetry show` in the server pod, without sending it. The command prints the data whether telemetry is on or off.

Test and development installs:

- **FR-011**: The E2E fixtures, docker-compose and `invoke dev` MUST NOT send reports to the production endpoint. Each one points the endpoint at a local sink or turns telemetry off.

Documentation, in the same change ([Constitution §VII](../../dev/constitution.md)):

- **FR-016**: The documentation page [`docs/docs/reference/telemetry.md`](../../docs/docs/reference/telemetry.md) MUST be renamed from "CLI telemetry & privacy" to "Telemetry & privacy" and MUST get a section for the server. That section lists every key in the report, states that driver names are sent as written and that a custom driver name can identify the operator's organisation, names the settings that turn telemetry off, names the default endpoint, and explains `styrmin telemetry show`.
- **FR-017**: `helm/styrmin/README.md` MUST document the Helm values `styrmin.telemetry.enabled` and `styrmin.telemetry.endpoint`.
- **FR-018**: A new ADR MUST record that driver names are sent as written and that the install ID is stored in the database.
- **FR-019**: `CONTEXT.md` MUST extend the **Telemetry** entry to cover the server and MUST add an **Install ID** entry.

### Key Entities

- **Install ID** (new): a random UUID that lets OpsMill count distinct installs without identifying them. One install is one Styrmin database. The install ID is stored in a new table that holds one row, and is created the first time the server starts. The PRD records that this database change was approved on 2026-10-08.
- **Telemetry report** (new): the data the server sends once a day, wrapped in the `styrminctl` envelope with `kind: "styrmin"`. It is built when it is sent or shown, and the server does not store it.
- **Application driver** and **application driver version** (existing): read only. The name, the version, the source type and the number of live deployments that use each version are reported.
- **Cluster**, **environment** and **deployment** (existing): counted only. Tombstoned deployments are not counted.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An install with default settings that is running at the time of the daily run has one report received at the endpoint within 24 hours of its first start.
- **SC-002**: With any one of the settings that turn telemetry off, the endpoint receives no request from the install.
- **SC-003**: Every received report contains only the keys listed in FR-006.
- **SC-004**: When the endpoint refuses connections, does not respond or returns errors, the install shows no failed flow runs and no telemetry log entries above debug level.
- **SC-005**: Within 30 days of the release that ships this feature, maintainers can answer both questions from the received reports: how many installs run each Styrmin version, and how many installs use each driver and driver version.

## Assumptions

- One install is one Styrmin database (PRD).
- Sending driver names as written is accepted, and the documentation page states it (PRD).
- The ingestion endpoint accepts anonymous POST requests without authentication, as ADR-047 assumes for `styrminctl` (PRD).
- Installs with workflows turned off are not normal production setups, because deployments do not run in that mode (PRD). As the edge cases note, `STYRMIN_WORKFLOW_ENABLE=false` does not turn workflows off in the current code.
- The Helm values and the environment variables reach every process that builds or sends a report: the server and the task worker, which runs the daily telemetry flow.
- `DO_NOT_TRACK` turns telemetry off only when its value is exactly `1`, as in `styrminctl`.
- The time of day of the daily run is not decided in the PRD. The plan chooses it.

## Out of Scope

From the PRD's "Out of scope for v1":

- Counting installs that are deleted before the daily run, such as short evaluation installs.
- Sending a missed report later. The install does not record when it last sent a report.
- A GraphQL query, a view in the web interface or a `styrminctl` command that shows the server report.
- Measuring how many installs turned telemetry off.
- Counts other than those in FR-006, such as users or backups.
- Telemetry from the **agent**.
- The ingestion endpoint, the storage of reports and dashboards.
- Changes to the GraphQL schema, the frontend, the SDK or `styrminctl`.

## Sources

- PRD: [opsmill/styrmin#274 (comment)](https://github.com/opsmill/styrmin/issues/274#issuecomment-6069930520)
- Issue: [#274](https://github.com/opsmill/styrmin/issues/274)
- `styrminctl` telemetry:
  - [ADR-047](../../dev/adr/0047-styrminctl-anonymous-fire-and-forget-telemetry.md)
  - [wire format](../archive/015-styrminctl-telemetry/contracts/telemetry-wire-format.md)
  - [documentation page](../../docs/docs/reference/telemetry.md)
  - [`eligibility.py`](../../cli/src/styrminctl/telemetry/eligibility.py) and [`config.py`](../../cli/src/styrminctl/telemetry/config.py)
- ADRs: [ADR-001](../../dev/adr/0001-alembic-database-migrations.md), [ADR-008](../../dev/adr/0008-deployment-soft-delete-tombstoning.md), [ADR-016](../../dev/adr/0016-authentication-and-sessions.md), [ADR-039](../../dev/adr/0039-single-cluster-platform-scope.md)
- Code: [`workflows/catalogue.py`](../../backend/styrmin_backend/workflows/catalogue.py), [`services/deployment.py`](../../backend/styrmin_backend/services/deployment.py), [Helm values](../../helm/styrmin/values.yaml)
- Project rules: [`CONTEXT.md`](../../CONTEXT.md), [`dev/constitution.md`](../../dev/constitution.md)
