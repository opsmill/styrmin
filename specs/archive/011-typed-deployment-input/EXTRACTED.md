# Extraction Record

**Extracted on**: 2026-05-16
**Extracted by**: speckit.extract

## ADRs Created

- `dev/adr/adr-026-typed-update-deployment-input.md` (from research §1, §3, §4, §5; data-model.md §1, §3, §4)

## Knowledge Updated

- `dev/knowledge/backend/api.md` — new "Deployment-config update + typed input" subsection added after "Environment-config update + fanout" (mirrors the 009 subsection structure; covers the mutation signature, full-replacement + `parameters`-merge asymmetry, list-shaped named fields with typed duplicate detection, error-code matrix, shared-leaf-inputs module layout, frontend submit-boundary helper).

## Guidelines Updated

None. The list-of-`{name, value}` convention for named-dict GraphQL inputs is prescriptive but folded into ADR-026 as the canonical source of truth; duplicating it under `dev/guidelines/backend/` would create two sources to keep in sync.

## Already Updated In-Line (not re-extracted)

The following in-line documentation updates landed during the feature's implementation phase (commit `9f6a393`) and did not need re-extraction:

- `dev/knowledge/backend/api.md` — mutation table row for `updateDeployment` already reflects the typed input signature.
- `dev/knowledge/backend/deployment-env-vars.md` — already references the typed `input: UpdateDeploymentInput!` argument and the post-cutover error reachability.

## Decisions Already Covered by Existing ADRs (not re-extracted)

- Hand-rolled Strawberry input pattern → [ADR-020](../../dev/adr/adr-020-environment-config-fanout.md) "Convention to replicate"
- Full-replacement typed input convention → [ADR-020](../../dev/adr/adr-020-environment-config-fanout.md) §2
- Clean-replace cutover (no deprecation window) → [ADR-020](../../dev/adr/adr-020-environment-config-fanout.md) §3
- Schema-walking propagation tests → [ADR-022](../../dev/adr/adr-022-schema-walking-input-propagation-tests.md)
- Frontend value-transform submit boundary → [ADR-023](../../dev/adr/adr-023-frontend-value-transform-boundary.md)

ADR-026 builds on all five and adds the spec's new content: list-shaped named-dict fields, `parameters`-merge asymmetry, two new typed errors, and the `config/inputs.py` shared-leaves extraction.

## Archive

Spec directory moved to `specs/archive/011-typed-deployment-input/` as a historical record.
