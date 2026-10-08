# PRD Alignment Check: Anonymous Daily Telemetry from the Styrmin Server

**Date**: 2026-10-08
**Spec**: [spec.md](spec.md)

## Source

- PRD "Anonymous daily telemetry from the Styrmin backend": [opsmill/styrmin#274 (comment)](https://github.com/opsmill/styrmin/issues/274#issuecomment-6069930520), fetched with `gh issue view 274 --comments` on 2026-10-08.
- The PRD's section "Differences from issue #274" was treated as part of the source, so where it overrides issue [#274](https://github.com/opsmill/styrmin/issues/274) the PRD wins.

## Verdict

⚠️ MINOR DRIFT (proceeding)

Every PRD goal, user story, functional requirement (FR-001 to FR-013 with the same numbers), success criterion, edge case, assumption and out-of-scope item is in the spec. Each "Verified by" clause of the PRD maps to a task in [tasks.md](tasks.md). The differences below are clarifications, one factual correction about the current code, and small additions, each marked `[CLAUDE RECOMMENDED]` in the spec. None changes what the PRD asks the feature to do.

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
|---|---|---|---|---|
| Minor | changed | Edge cases: "Workflows are turned off (`STYRMIN_WORKFLOW_ENABLE=false`): the daily flow does not run, so no report is sent." | Edge cases, Assumptions; [research D15](research.md) | No code reads `STYRMIN_WORKFLOW_ENABLE`, so the PRD's statement is not true of the current code. The spec says so and points operators to the telemetry settings. It does not add a check, because that would give the setting a meaning for one flow only. |
| Minor | added | Configuration: one Helm value, `styrmin.telemetry.enabled` | FR-020 | New Helm value `styrmin.telemetry.endpoint`. FR-011 needs the E2E install to send to a sink, and the chart has no other way to set an environment variable. |
| Minor | added | Open question: default endpoint URL not decided | FR-015 | The spec chooses `https://telemetry-endpoints.cloudflare-096.workers.dev/styrmin`, by analogy with the `styrminctl` path. Marked as a recommendation; the owner of the ingestion endpoint confirms it before the release (plan "Release prerequisite"). |
| Minor | added | Implementation decisions: install ID store "creates it the first time" | FR-014 | A failure to create the install ID does not stop the server from starting. From issue #274 ("never block or degrade the backend") and critique finding E2. |
| Minor | added | User story 7 (log line) | FR-017 | The chart's `NOTES.txt` also says whether telemetry is on (critique P2). |
| Minor | added | User story 9; FR-011 lists E2E, docker-compose, `invoke dev` | plan D18, task T037 | The local demo values (`dev/local/demo-values.yaml`) also turn telemetry off. Plan and tasks only; the spec's FR-011 is unchanged. |
| Minor | changed | FR-001: "every loaded driver version" | FR-001 (added paragraph) | Driver versions that differ only in the fields FR-002 removes are merged into one entry with their counts added, because the endpoint could not tell them apart ([research D9](research.md)). |
| None | clarification | Edge cases: "the missed report is not sent later" | Edge cases; [research D14](research.md) | Prefect runs a missed run when the task worker comes back. The plan skips runs that start more than one hour late, which makes the PRD's statement true. |
| None | clarification | FR-001, FR-006: "live deployments" | Edge cases | Internal ingress controller deployments are counted like other live deployments. |
| None | clarification | FR-013 | User Story 3, scenario 3; FR-013 | `styrmin telemetry show` also works when telemetry is off. |

No PRD requirement, acceptance criterion or non-goal is missing, softened or contradicted.

## Action

Proceed. No remediation pass was needed (0 of 2 used). The FR-001 paragraph about merged driver entries was added to the spec during this check, so the spec states a decision the plan had already made.
