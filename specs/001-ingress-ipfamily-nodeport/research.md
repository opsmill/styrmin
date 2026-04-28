# Phase 0 Research: IP Family & Fixed NodePort Knobs

The spec arrives with most decisions pinned (the source GitHub issue is concrete). This phase resolves the few remaining unknowns to a level the implementer can act on without further look-ups.

## R1 — Traefik chart 28.2.0 keys for IP family pinning and per-entrypoint NodePort

**Decision**:

- IP families: `service.ipFamilies` (list of `"IPv4"` / `"IPv6"`).
- IP family policy: `service.ipFamilyPolicy` (one of `"SingleStack"` / `"PreferDualStack"` / `"RequireDualStack"`).
- Per-entrypoint NodePort overrides: `ports.web.nodePort` and `ports.websecure.nodePort` (integers).

**Rationale**: The chart in use is pinned at version `28.2.0` by `backend/styrmin_backend/services/ingress_controller/driver.py`. The chart's `values.yaml` schema places `ipFamilies` / `ipFamilyPolicy` directly under the `service:` block (mirroring the Kubernetes Service object shape) and per-entrypoint NodePort overrides under each entry of `ports:` keyed by entrypoint name. The GitHub issue body confirms these key paths. No alternate keys are exposed by the chart for these knobs.

**Alternatives considered**:

- Setting `nodePort` at the Service level (rather than per-entrypoint) — rejected because the Traefik chart does not expose a top-level Service-NodePort key; the per-entrypoint override is the only path.
- Splitting `node_port` into `{web: int, websecure: int}` — out of scope for this iteration per FR-010 and the spec's Assumptions; tracked as a future extension if a recipe needs divergent ports.

## R2 — Jinja rendering pattern (matches existing conditional fields)

**Decision**: Mirror the conditional pattern already used for `load_balancer_ip` and `external_traffic_policy` in `chart_values.j2.yaml`. Each new key is rendered inside an `{% if … %}` block keyed on the corresponding config attribute being non-`None`. The three new conditionals attach to:

- `service.ipFamilies` and `service.ipFamilyPolicy` — rendered inside the existing top-level `service:` block alongside `loadBalancerIP` and `externalTrafficPolicy`.
- `ports.web.nodePort` and `ports.websecure.nodePort` — rendered as a new top-level `ports:` block emitted **only** when `node_port` is set; the commented-out `ports:` scaffold at lines 49–55 is removed in the same edit (nothing emits it today; FR-011 byte-identical guarantee is unaffected because comments are not part of the byte-stream produced by the rendered values consumer — to be verified by a snapshot test).

**Rationale**: Reusing the established conditional pattern minimizes review surface, keeps the template's idiom consistent, and ensures the byte-identical guarantee for unset fields is achieved by the same mechanism that already keeps `loadBalancerIP` / `externalTrafficPolicy` out of the output when unset.

**Alternatives considered**:

- A single `{% if any-new-field-set %}` umbrella — rejected because the three fields are independently optional; per-field conditionals are the natural fit.
- Always rendering the keys with `null` defaults — rejected because the chart treats explicit `null` differently from "key absent" in some places, and the byte-identical guarantee (FR-011) requires absence.

**Snapshot guarantee verification**: The existing snapshot tests at `backend/tests/unit/services/test_ingress_controller.py:178-192` capture the current rendered output. The implementation MUST keep those snapshots passing unchanged. The "remove the commented-out scaffold" edit must therefore not alter the byte-stream the snapshot captures — which is the case because the scaffold is comment-only YAML and the renderer's consumer (the helm value loader) ignores comments. The snapshot test asserts the parsed-and-re-emitted values; a manual diff of the literal template text (comments included) is *not* what the snapshot covers. If a future refactor adds literal-text snapshotting, this assumption must be revisited.

## R3 — Pydantic v2 validator patterns for the two cross-field constraints

**Decision**:

- `ip_families` non-empty + no-duplicates: implement as a `@field_validator("ip_families", mode="after")` that raises `ValueError` when the list is empty or contains duplicates.
- `node_port` is only valid when `type == "NodePort"`: implement as a `@model_validator(mode="after")` that raises `ValueError` when `self.node_port is not None and self.type != "NodePort"`. The error message names both fields (`type` and `node_port`) so the operator can correct either side.

**Rationale**: Pydantic v2 separates field-scoped checks (`field_validator`) from cross-field checks (`model_validator`). The IP family list validator only inspects one field, so `field_validator` is correct. The `node_port`-vs-`type` constraint inspects two fields, requiring `model_validator(mode="after")`. Both raise `ValueError`, which Pydantic wraps into a `ValidationError` at construction — the standard config-load failure mode. Existing models in the same file (e.g., `DeploymentReference._require_one_identifier` at `config.py:138-144`, `WeightedAffinityTerm._weight_range` at `config.py:182-187`, `ResourceSpec._validate_quantities` at `config.py:229-237`) already follow this exact pattern, so the new validators slot into the established idiom.

**Alternatives considered**:

- Encode the `ip_families` constraint via `pydantic.types.conlist(min_length=1, unique_items=True)` — rejected because Pydantic v2 dropped `unique_items` from the public list-constraint API; an explicit field validator is now the canonical path.
- Implement the cross-field check as a pre-validator (`mode="before"`) — rejected because the inputs are not yet coerced to the model's typed shape, so the check is fragile against unparsed payloads. `mode="after"` runs against fully-validated field values and is the safer default.

## R4 — GraphQL / SDK / frontend impact

**Decision**: None. No GraphQL schema regeneration, no SDK regeneration, no frontend work.

**Rationale**: The existing `IngressServiceConfig` fields (`type`, `annotations`, `load_balancer_ip`, `external_traffic_policy`) appear only in the Pydantic model (`backend/styrmin_backend/context/models/config.py`), the chart-values template (`backend/styrmin_backend/services/ingress_controller/templates/chart_values.j2.yaml`), and the unit tests (`backend/tests/unit/services/test_ingress_controller.py`). Grep across `backend/styrmin_backend/api/`, `frontend/`, and `python_sdk/` finds zero references to those fields, confirming `IngressServiceConfig` flows as a JSON sub-tree of the cluster/environment `config` blob — not as a typed GraphQL object with per-field exposure. Adding three more optional fields to the same Pydantic model rides the same JSON path with no additional surface to update. AGENTS.md's "regenerate `schema.graphql` after any GraphQL schema change" rule is therefore not triggered.

**Alternatives considered**:

- Promote the new fields to typed GraphQL/SDK exposure — rejected because (a) the existing fields do not have such exposure and parity is the right baseline, and (b) the operator path that the spec's user stories require is the same one that already sets the existing fields, which is config-blob ingestion (cluster/environment context).

## R5 — E2E extension shape

**Decision**: Add a new test function (or parametrize an existing one) to `backend/tests/e2e/test_ingress_controller.py` that creates an environment with `dedicated_ingress.service.type = "NodePort"` and `dedicated_ingress.service.node_port = <port>`, deploys, and asserts:

1. The Traefik Service object in-cluster is `type: NodePort`.
2. Both the `web` and `websecure` Service ports report the chosen `nodePort` value.
3. After a Service deletion + reconcile, the NodePort value is unchanged.

The test reuses the existing `vcluster` and `styrmin_resources` fixtures (single-family). No new fixture, no new module.

**Rationale**: FR-013 / SC-006 require extending the existing E2E module rather than spawning a new one. The existing module already wires up cluster + environment + scenario-driver fixtures; adding a NodePort scenario costs only a function. A NodePort Service comes up identically on a single-family cluster, so the test exercises the full rendering + apply + observe cycle without needing dual-stack infrastructure.

**Alternatives considered**:

- Add a separate `test_ingress_nodeport.py` module — rejected by the explicit constraint in the clarification answer ("re-use existing E2E test if possible — do not introduce a new one").
- Verify NodePort by `kubectl describe service` text-scraping — rejected; the existing tests use `kr8s` typed objects (`AsyncService`), and those expose `.spec.ports` directly with no scraping.

## R6 — IPv6/dual-stack manual-validation runbook (FR-013, SC-006)

**Decision**: Publish a short Markdown runbook at `dev/guides/ingress-ipv6-dual-stack-validation.md` with three sections:

1. Pre-flight: confirming the target cluster is dual-stack (`kubectl get nodes -o wide` shows IPv6 addresses; `kubectl get --raw /api/v1/nodes` reports both families).
2. Apply a known-good config: an environment config snippet with `dedicated_ingress.service.ip_families: ["IPv6"]` and `ip_family_policy: "SingleStack"`.
3. Observation steps: `kubectl get service -n <ingress-ns> -o yaml` and confirm the rendered Service reports `spec.ipFamilies: [IPv6]` and `spec.ipFamilyPolicy: SingleStack`; `dig AAAA <fqdn>` resolves; from a v6-capable client a request reaches the Service.

**Rationale**: Operators who hit the Cloudflare/Infrahub recipe need a deterministic procedure to verify the pinning, and §V's escape-hatch (recorded in spec Clarifications) made this runbook a contractual deliverable rather than an optional doc.

**Alternatives considered**:

- Inline the runbook in the spec — rejected because operators will look in `dev/guides/` for how-to material; the spec is for stakeholder/reviewer use.
- Defer the runbook to "after the follow-up automated dual-stack E2E lands" — rejected because the runbook *is* the bridge until the automated coverage exists, and shipping the feature without it leaves operators without verification steps.
