# Extraction Record

**Extracted on**: 2026-10-17
**Extracted by**: speckit.opsmill.extract

## ADRs Created

- dev/adr/0076-teardown-deletes-service-aliases-in-all-namespaces.md (from R-001, R-002, R-011)
- dev/adr/0077-alias-flow-reads-deletion-state-at-write-time.md (from R-003, R-004, R-005)
- dev/adr/0078-alias-step-reads-current-services-from-server.md (from R-012)

ADR number 0075 was skipped because branch `fac/affinity-by-id-zsdtf` already uses it.

## Knowledge Updated

- dev/knowledge/backend/orchestration-flows.md (Service aliases: the table of what the flow's two reads decide over a deployment's life, from data-model.md, checked against `_is_departing` and `_is_deployment_deleted`)
- dev/knowledge/backend/orchestration-flows.md (Key Files: `service_aliases.py`, `environment_services.py`, `service_alias_rules.py`)
- dev/knowledge/agent/overview.md (Directory structure, Key files: the alias flow, the environment-services read, the shared alias rules and the StyrminDeployment read)

## Guides Updated

- dev/guides/e2e-deployment-sharing.md (Tiers: `test_service_discovery` moved from the read-only examples to the isolated-mutation examples, because its last test deletes `intent`)

## Guidelines Updated

- dev/guidelines/backend/python.md (Rendering Kubernetes manifests: "Delete an object that another writer can replace with a `resourceVersion` precondition", from R-004 and FR-004)
- dev/guidelines/backend/python.md (Rendering Kubernetes manifests: "Never create another deployment's namespace", from R-005)
- dev/guidelines/backend/python.md (Rendering Kubernetes manifests: "Delete objects outside a deployment's namespace only for a requested deletion", from R-001 and R-011)
- dev/guidelines/backend/python.md (Prefect Flows & Tasks: "Read state that another deployment changes when you write, not from the flow's context", from R-003, R-004 and R-012)

## Already Documented During Implementation

- dev/knowledge/agent/operator.md (Deletion: the teardown's alias step)
- dev/knowledge/backend/orchestration-flows.md (Service aliases: the rules of both reads, the server read, no namespace creation, the restore case)
- CONTEXT.md (Service alias)
- dev/adr/0073-kubernetes-objects-named-and-found-by-record-id.md (More information: the known case for deployment deletion removed)

## Not Extracted

- R-006: no change; a unit test covers it.
- R-007: test only. That Kubernetes accepts the change of `spec.type` from `ExternalName` to `ClusterIP` comes from the Kubernetes documentation, not from a cluster run.
- R-008: the place of the E2E test in its module; the test file shows it.
- R-009: no dependency or governance gate.
- R-010: follow-up issue [#527](https://github.com/opsmill/styrmin/issues/527).
- pr-notes.md: the question whether a unit test is enough for an alias that a failed teardown left is not answered.

## Archive

Spec directory moved to `specs/archive/026-delete-service-aliases/` as a historical record.
