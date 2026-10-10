# Extraction Record

**Extracted on**: 2026-10-10
**Extracted by**: speckit.opsmill.extract

## ADRs Created

None. [ADR-061](../../../dev/adr/0061-server-anonymous-daily-telemetry.md), written during the
implementation, already records research D1–D19. Its Source line now points at this archive
directory.

## Knowledge Updated

- `dev/knowledge/backend/services.md` (new section "Telemetry Services (`services/telemetry/`)", Key Files)
- `dev/knowledge/backend/overview.md` (Entry Point: startup sequence rewritten to match `server/app.py`)
- `dev/knowledge/backend/overview.md` (Settings loading: `STYRMIN_WORKFLOW_ENABLE` is not read by any code, from D15)

## Guidelines Updated

- `dev/guidelines/backend/python.md` (Prefect Flows & Tasks: "Decide whether a cron flow acts when its run starts late", from D14)
- `dev/guidelines/backend/python.md` (new section "Outbound HTTP requests", from D8)
- `dev/guidelines/helm.md` (new section "Read values that a chart upgrade adds with `dig`", from contracts/configuration.md)

## Already Documented During Implementation

- `dev/adr/0061-server-anonymous-daily-telemetry.md`
- `dev/knowledge/backend/data-models.md` (`Installation`)
- `dev/knowledge/backend/orchestration-flows.md` (`SEND_TELEMETRY_REPORT` and its schedule)
- `dev/knowledge/architecture.md`, `dev/knowledge/backend/e2e-testing.md` (telemetry sink)
- `CONTEXT.md` (Telemetry, Install ID), `docs/docs/reference/telemetry.md`

## Other Changes

- `CLAUDE.md`: the "Active feature plan" link points at the archive path.

## Archive

Spec directory moved to `specs/archive/020-backend-telemetry/` as a historical record.
