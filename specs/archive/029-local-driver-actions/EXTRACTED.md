# Extraction Record

**Extracted on**: 2026-10-20
**Extracted by**: speckit.opsmill.extract

## ADRs Created

None. ADR-081 (dev/adr/0081-local-driver-actions-check-their-files-at-the-driver-path.md) was written during implementation and amended on 2026-10-20. It records R-001 to R-010, the error texts that name the agent pod, and the Job of `execute_commands`. R-011 is the E2E design, R-012 decides to change nothing, and R-013 is in `docs/docs/drivers/loading-drivers.md`.

## Knowledge Updated

- dev/knowledge/backend/orchestration-flows.md (Remediation-flow steps: hook steps that `apply_state` and `update_deployment_version` record as failed)
- dev/knowledge/backend/services.md (Deployment service table: the failed task that `update_deployment_version` returns when an upgrade action has no registered flow)
- dev/knowledge/cli/overview.md (A version change that returns a failed task: SDK `update_version()` and `apply`, `styrminctl deployments update-version`)
- dev/knowledge/backend/e2e-testing.md (Key Files; Driver files in the server pod and the agent pod)

Updated during implementation, before extraction: dev/knowledge/backend/hooks-and-actions.md, dev/knowledge/agent/overview.md, dev/knowledge/backend/api.md, dev/knowledge/backend/data-models.md, dev/knowledge/backend/overview.md, dev/guides/driver-iteration.md, dev/adr/0053-driver-version-provenance-fingerprint.md, CONTEXT.md, driver/DRIVERS.md and the pages under docs/docs/.

## Guidelines Updated

- dev/guidelines/backend/python.md (Logging → Redact the text of a flow run's logs before it goes into a step or a task)
- dev/guidelines/backend/python.md (Service Layer → Look up the flows of a hook only through `services/driver/hooks.py`)
- dev/guidelines/backend/python.md (Service Layer → Record a failure that a request check finds on a failed task with no flow run)
- dev/guidelines/backend/python.md (Rendering Kubernetes manifests → Delete the earlier Job of a name built from an id only when it has ended and Styrmin created it)
- dev/guidelines/backend/python.md (Prefect Flows & Tasks → Refuse `{` and `}` in a user value that goes into a Prefect pull step: the path of a local driver version)
- dev/guidelines/backend/python.md (Prefect Flows & Tasks → Log the error of a pull step in the flow run before it raises)
- dev/guidelines/backend/python.md (Testing → pin `driver_version_id` in an E2E test that loads more than one variant of a driver)

## Links Updated

Links to `specs/029-local-driver-actions/` now point to `specs/archive/029-local-driver-actions/` in ADR-081, ADR-053, dev/knowledge/backend/services.md, dev/knowledge/backend/hooks-and-actions.md, CLAUDE.md, and the docstrings of `services/driver/hooks.py`, `services/driver/labels.py` and `backend/tests/e2e/test_infrahub_local_driver_actions.py`.

## Archive

Spec directory moved to `specs/archive/029-local-driver-actions/` as a historical record.
