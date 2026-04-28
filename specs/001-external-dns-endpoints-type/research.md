# Phase 0: Research — external-dns endpoints-type

**Status**: All NEEDS CLARIFICATION items resolved (the spec carries zero markers; the single open decision was settled in `## Clarifications` during `/speckit.clarify`).

This document records the technical-context decisions that drive Phase 1 design, with rationale and the alternatives considered.

---

## Decision 1: Place the field on `BaseConfigSection`

**Decision**: Add `external_dns_endpoints_type: Literal["NodeExternalIP", "ClusterIP"] | None = None` to `BaseConfigSection` in `backend/styrmin_backend/context/models/config.py`, alongside `ingress_class`, `fqdn_suffix`, `external_url_scheme`, and `external_url_port`.

**Rationale**:

- `BaseConfigSection` is the shared parent of `ClusterConfig`, `EnvironmentConfig`, and (transitively, via `DeploymentConfig`) `ResolvedConfig`. Adding the field here makes it accepted at every layer with zero per-layer plumbing.
- The Cluster → Environment → Deployment merge already in place for `fqdn_suffix` / `ingress_class` propagates the value to `ResolvedConfig` automatically. No new merge code, no risk of layer-skew.
- Sibling fields (`ingress_class`, `external_url_scheme`) already use the same `Literal | None = None` pattern with `model_config = ConfigDict(extra="forbid")`. Mirroring the pattern keeps the model coherent.

**Alternatives considered**:

- *Place the field on `ClusterConfig` only.* Rejected: the issue's acceptance criteria (and the spec's FR-002) require the value to be settable at any of the three layers, with deployment-level override beating cluster-level. A cluster-only field would force operators to clone clusters whenever a single deployment needed a different value.
- *Introduce a new sub-model `ExternalDnsConfig` carrying `endpoints_type` (and future siblings).* Rejected for now: there's exactly one field, and the issue notes that broader external-dns plumbing is out of scope for this feature. Premature abstraction; the flat-field shape matches `fqdn_suffix` / `ingress_class` precedent. If/when more external-dns knobs land, a refactor to a nested object is cheap.
- *Use a string field with a runtime validator.* Rejected: `Literal[...]` gives Pydantic-level validation at config-parse time, satisfies FR-005's "config-parse time, not reconcile-time" requirement, and produces a clear, auto-generated error message that names the offending field and lists accepted values — no custom validator required.

---

## Decision 2: Emit the annotation in `IngressUtility.build_app_post_rendering_patches`

**Decision**: In `backend/styrmin_backend/agent/service/kubernetes/resources/utilities/ingress.py`, after constructing the existing `annotations` dict (lines 32–37) and before the `dedicated_ingress` / `ingress_class` branch, conditionally insert:

```python
if context.instance.config.external_dns_endpoints_type is not None:
    annotations["external-dns.alpha.kubernetes.io/endpoints-type"] = (
        context.instance.config.external_dns_endpoints_type
    )
```

**Rationale**:

- The existing code already reads `context.instance.config.fqdn_suffix` and `.ingress_class` from the same `ResolvedConfig`. Reading one more field is the same pattern.
- Placing the conditional after the base annotations are constructed but in the same dict satisfies FR-003 ("annotation MUST sit in the same annotation dictionary as `hostname` and `cloudflare-proxied`").
- Skipping the insert when the value is `None` satisfies FR-004 ("MUST NOT inject a runtime default; rest of annotation set MUST be unchanged").

**Alternatives considered**:

- *Always emit the annotation, defaulting to `"ClusterIP"` when unset.* Rejected: the issue explicitly forbids runtime defaulting and the spec captures this in FR-004 — the "do not emit" state is part of the contract and is what preserves byte-identical output for existing deployments (SC-002).
- *Emit the annotation in the Jinja2 values template instead of in `build_app_post_rendering_patches`.* Rejected: the existing `external-dns` annotations are emitted through the post-rendering-patch path, not the values template. Splitting one annotation set across two emission sites would break the locality of FR-003.

---

## Decision 3: No DB migration, no GraphQL schema change

**Decision**: Make zero changes to:

- `backend/styrmin_backend/db/models.py` (Cluster/Environment/Deployment `config` columns are already `JSON`)
- `schema.graphql` and the SDK-generated Pydantic types (the `create_cluster` / `create_environment` / `create_deployment` mutations already accept `config: JSON | None`)

**Rationale**:

- Verified by inspecting the existing fields: `fqdn_suffix` and `ingress_class` exist on `BaseConfigSection` but appear nowhere in `db/models.py` or in the GraphQL schema as typed fields. They are part of the JSON blob stored in the `config` column and validated server-side at deserialisation by Pydantic. Adding a new sibling on the same Pydantic model inherits the same boundary.
- Avoids triggering the constitution's Governance Gates (DB schema, GraphQL schema modifications), which would require explicit prior discussion.
- Zero migration cost. Operators upgrading to a release that ships this feature have their existing config blobs accepted unchanged (the field is `Optional` with default `None`).

**Alternatives considered**:

- *Promote the field to a typed GraphQL input.* Rejected: would require GraphQL schema regeneration and SDK regeneration, adds a typed surface that operators don't need (config payloads are already JSON-blob-shaped end-to-end), and triggers the GraphQL governance gate for what is a one-line internal-model change.

---

## Decision 4: Test scope — four render-tier unit tests + two validation tests + one E2E assertion bolt-on

**Decision**: Add **four** test methods to `TestIngressUtilityPostRenderingPatches` in `backend/tests/unit/agent/test_utility_resources.py`:

1. `test_includes_endpoints_type_when_node_external_ip` — sets `external_dns_endpoints_type="NodeExternalIP"` directly on the resolved instance config, asserts the annotation is present with that value.
2. `test_includes_endpoints_type_when_cluster_ip` — same with `"ClusterIP"`.
3. `test_omits_endpoints_type_when_unset` — leaves the field at its `None` default, asserts the annotation key is absent from the dict.
4. `test_deployment_overrides_cluster_endpoints_type` — builds a `ClusterConfig(external_dns_endpoints_type="NodeExternalIP", …)`, an `EnvironmentConfig()` with the field unset, and a `DeploymentConfig(external_dns_endpoints_type="ClusterIP")`. Calls `_resolve_instance_config(cluster, environment, deployment)` from `styrmin_backend.context.resolvers` to compute the resolved config, builds a `GlobalContext` from it, and asserts the rendered Ingress annotation equals `"ClusterIP"`. This single test discharges FR-002 (merge precedence), US1 Acceptance Scenario 3, and the "Field set at multiple layers" edge case.

Create a separate focused file `backend/tests/unit/context/test_base_config_section.py` with two validation tests covering FR-005 / US2:

5. `test_validation_rejects_invalid_endpoints_type` — `ClusterConfig(external_dns_endpoints_type="PodIP")` raises `pydantic.ValidationError` whose payload names the field and lists `'NodeExternalIP'` / `'ClusterIP'`.
6. `test_validation_accepts_explicit_null` — `ClusterConfig(external_dns_endpoints_type=None)` succeeds and round-trips with `None`.

Validation tests live in a separate file because they are about the config model's invariants, not about the IngressUtility's rendering behaviour. The issue's acceptance criteria suggested `test_utility_resources.py` for the *render* tests only; the constitution's layered-architecture principle prefers colocating model tests with the models.

Add **one** assertion to the existing `test_deploy_with_dedicated_ingress` E2E test in `backend/tests/e2e/test_ingress_controller.py`, after the existing `kubernetes.io/ingress.class` check, asserting that `external-dns.alpha.kubernetes.io/endpoints-type == "NodeExternalIP"`. Set the field at the session cluster fixture in `backend/tests/e2e/conftest.py` (line 665, `cluster = await driver.create_cluster(...)`) by adding `"external_dns_endpoints_type": "NodeExternalIP"` to the cluster config dict.

**Rationale**:

- Mirrors the existing test pattern: `test_includes_external_dns_hostname` and `test_includes_cloudflare_proxied` already assert specific annotations from this dict. The three single-state render tests (#1–#3) plus one merge-precedence test (#4) keep the render-tier coverage in one class.
- Test #4 specifically exercises the merge function `_resolve_instance_config` (`backend/styrmin_backend/context/resolvers.py:66-93`), which uses `**cluster.model_dump(exclude_none=True), **environment.model_dump(...), **deployment.model_dump(...)` — generic dict-spread merging that propagates any new `BaseConfigSection` field automatically with deepest-wins precedence. The test pins this contract for the new field so a future regression in the merge cannot silently flip the rendered annotation.
- Setting the field at the **cluster** layer in E2E (not deployment) exercises the cluster→resolved inheritance path — the resolved config picks the value up via the Cluster → Environment → Deployment merge, which is exactly the production scenario operators will use.
- Setting `"NodeExternalIP"` at the cluster fixture means *every* deployment created against that cluster (across all E2E tests) will carry the annotation. This is benign: no other E2E test asserts the *absence* of arbitrary annotations on the rendered Ingress, so adding an extra annotation is non-breaking.
- Satisfies the spec's clarification (extend existing, do not create new) and the constitution's E2E mandate.

**Alternatives considered**:

- *Create a new test scenario `test_deploy_with_node_external_ip_endpoints`.* Rejected by the spec's `## Clarifications` decision — creating a parallel scenario duplicates the vcluster + ingress-controller fixture cost (~3 minutes per run) for one extra annotation assertion.
- *Place the merge-precedence test in `test_base_config_section.py` (the new US2 file) instead of in `TestIngressUtilityPostRenderingPatches`.* Rejected: US1 Acceptance Scenario 3 says "the rendered Ingress carries `endpoints-type: ClusterIP`" — the spec's contract is on the rendered output, not just on the resolved config field. Routing the test through `build_app_post_rendering_patches` matches the contract and reuses the existing class's setup pattern.
- *Place the US2 validation tests in `test_utility_resources.py` next to the render tests.* Rejected: validation belongs with the config model, not with the renderer. Putting them next to the merge-precedence test would conflate three concerns (rendering, merging, validating) in one file.
- *Set the E2E field at the environment layer.* Equivalent in behaviour to cluster-layer but doesn't match how operators are most likely to configure this (cluster-wide is the IPv6-cluster recipe). Cluster-layer reflects production usage.

---

## Decision 5: No agent-context update

**Decision**: Do **not** run `.specify/scripts/bash/update-agent-context.sh` despite the speckit-plan template's Phase 1 step listing it.

**Rationale**: The Styrmin constitution explicitly lists this script under `Boundaries → Never`: *"Execute the script `update-agent-context.sh` — agent context files are maintained manually or through other workflows."* The constitution overrides the template here.

**Alternatives considered**: None — the constitution is unambiguous.

---

## Open Questions

None. All Technical Context fields are populated with concrete values; no `NEEDS CLARIFICATION` markers remain. The single decision flagged during `/speckit.clarify` (E2E scope) was resolved and recorded in the spec's `## Clarifications` section.
