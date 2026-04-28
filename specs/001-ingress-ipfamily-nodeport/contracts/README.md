# Contracts — none

This feature adds **no API contracts**. There are no new GraphQL types, no new mutations or queries, no new REST endpoints, and no new SDK methods.

## Why

`IngressServiceConfig` is consumed as a JSON sub-tree of the cluster/environment `config` field, not as a typed GraphQL/SDK object. Verified by grep across `backend/styrmin_backend/api/`, `python_sdk/`, and `frontend/`: the existing fields (`type`, `annotations`, `load_balancer_ip`, `external_traffic_policy`) appear only in:

- `backend/styrmin_backend/context/models/config.py` (the Pydantic model)
- `backend/styrmin_backend/services/ingress_controller/templates/chart_values.j2.yaml` (the chart-values template)
- `backend/tests/unit/services/test_ingress_controller.py` (unit tests)

Adding three more optional Pydantic fields to the same model rides the same JSON path with no additional API surface to update. AGENTS.md's "regenerate `schema.graphql` and SDK after any GraphQL schema change" rule is therefore not triggered for this feature.

## Operator-facing contract

The user-facing contract is the Pydantic model itself — see [data-model.md](../data-model.md). Operators interact with it the same way they already set `load_balancer_ip` or `external_traffic_policy`: by editing the cluster or environment `config` blob (via whatever path the platform already provides for that — config files, GraphQL `updateCluster` / `updateEnvironment` mutations carrying the JSON config, etc.).
