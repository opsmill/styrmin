# Extraction Record

**Extracted on**: 2026-10-13
**Extracted by**: speckit.opsmill.extract

## ADRs Created

None. [ADR-066](../../../dev/adr/0066-cluster-config-fanout.md) was written during
implementation and already records research.md D1–D7 and D12.

## ADRs Amended

- [dev/adr/0066-cluster-config-fanout.md](../../../dev/adr/0066-cluster-config-fanout.md)
  - §2: corrected the wording of the rule that makes an application wait for the dedicated ingress controller, and recorded its limitation for deployments that set their own `dedicated_ingress`.
  - Alternatives: the unknown-key check is restored in the SDK, and so in the CLI.
  - `Source` and the e2e-evidence path point at `specs/archive/021-cluster-config-update/`.
- [dev/adr/0029-config-additions-via-baseconfigsection-no-migration.md](../../../dev/adr/0029-config-additions-via-baseconfigsection-no-migration.md) (narrowed by ADR-066: every config level has a typed update input with a parity test, so a new `BaseConfigSection` field needs schema work)

## Knowledge Updated

- `dev/knowledge/backend/api.md` (new "Cluster-config update + typed input"; shared leaf inputs paragraph)
- `dev/knowledge/backend/services.md`
  - directory tree
  - Capabilities Service: callers
  - Deployment table: ingress controller functions
  - Environment-config fanout: `update_environment` never touches the dedicated ingress controller
- `dev/knowledge/backend/data-models.md` (config merge; DedicatedIngressConfig; IngressServiceConfig)
- `dev/knowledge/backend/orchestration-flows.md` (task types of reconcile tasks)
- `dev/knowledge/architecture.md` (§3.5: a failed rollout is not retried by resubmitting; StatefulSet `volumeClaimTemplates`)
- `dev/knowledge/cli/overview.md` (Overview; new "Cluster config update")
- `dev/knowledge/frontend/forms.md` (Overview; Cross-Field Validation; new "Cluster config form (create and edit)")
- `dev/knowledge/backend/e2e-testing.md` (Markers: `changes_cluster_config`)
- `dev/knowledge/agent/operator.md` (Platform-driven deletion: kopf finalizer race, issue #446)
- `dev/knowledge/agent/overview.md` (new "Cluster config fan-out after a state change")
- `CONTEXT.md` (new term "Dedicated ingress controller")

## Guidelines Updated

- `dev/guidelines/backend/python.md`
  - Per-target failure isolation in fanout writes: rewritten, because the old text called a function that does not exist
  - Take a typed input that mirrors the config model in a mutation that writes a config
  - Never let work added to a status report fail the report
  - Calculate a status that several writers change; do not store it: the waiting-for-ingress example
- `dev/guidelines/frontend/forms.md` (Keep the values an edit form does not show when it submits a full-replacement input)

## Other Changes

- `driver/DRIVERS.md`: the naming-convention example reads `instance.config.*`.
- `python_sdk/AGENTS.md`: new "Updating a cluster config".
- `backend/tests/functional/graphql/test_cluster_update_propagation.py`: docstring path points at `specs/archive/021-cluster-config-update/`.
- `CLAUDE.md`: removed the "Active feature plan" line for this spec.

## Already Documented Before Extraction

- ADR-066, and the status note on ADR-012
- `dev/knowledge/architecture.md` (cluster config fan-out), `dev/knowledge/backend/services.md` ("Cluster config fan-out"), `dev/knowledge/backend/api.md` (`updateCluster` row)
- `dev/guides/e2e-parallelism.md` ("Tests that change the cluster config")
- `docs/` pages for the cluster config update

## spec.md Changes at Extraction

- `**Status**` set to `Extracted`.

## Archive

Spec directory moved to `specs/archive/021-cluster-config-update/` as a historical record.
