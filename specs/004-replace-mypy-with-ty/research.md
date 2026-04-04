# Research: Replace mypy with ty

## Decision 1: Orphaned `# type: ignore` Comment Strategy

**Decision**: Remove all `# type: ignore` comments that are not needed by ty, then re-run `ty check` with `unused-type-ignore-comment` enabled to verify.

**Rationale**: After removing mypy, the `# type: ignore` comments that were only needed by mypy become orphaned. ty has its own `unused-type-ignore-comment` rule that will flag these. The approach is: (1) enable the rule, (2) run `ty check` to find orphaned comments, (3) remove them iteratively until `ty check` passes.

**Alternatives considered**:
- Remove all `# type: ignore` comments at once: Too aggressive — some may still be needed by ty.
- Keep all comments: Would leave noise in the codebase and the `unused-type-ignore-comment` rule would still flag them.

## Decision 2: ty Rule Audit Approach

**Decision**: Enable each suppressed ty rule one at a time per module, analyze the violations, and categorize them.

**Rationale**: Enabling rules one at a time makes it easy to understand the scope of each rule's impact and decide whether to fix violations or keep the suppression. Batch-enabling would make it hard to attribute errors.

**Categories**:
- **Fixable now**: Genuine type errors that can be resolved with code/annotation changes.
- **Upstream blocker**: False positives from Strawberry GraphQL, SQLAlchemy, or Pydantic where ty support is still maturing. These are documented and suppressed.
- **Generated code**: Rules triggered in `_generated/` directories. Suppressions remain.

**Alternatives considered**:
- Enable all rules at once: Too many errors to triage effectively.
- Only enable rules with zero violations: Misses the goal of reducing suppressions by 50%.

## Decision 3: Constitution Update

**Decision**: Update the constitution's Principle IV to reference ty instead of mypy.

**Rationale**: Principle IV currently says "Python type hints are mandatory (enforced by mypy with `disallow_untyped_defs`)". After migration, this must reflect ty as the enforcement tool. The `disallow_untyped_defs` behavior is already covered by ty's default rules.

## Decision 4: `lint_ty` Task Registration

**Decision**: Register `lint_ty` as a standalone invoke task in `tasks/format.py` (add to `ns`) to replace `lint_mypy`.

**Rationale**: Currently `lint_ty` is defined in `tasks/format.py` but not registered in the collection's `ns.add_task()` calls. It's only called indirectly via `lint_all()` in `tasks/__init__.py`. After removing `lint_mypy`, `lint_ty` should be properly registered so developers can run it standalone.

## Decision 5: Stub Package Removal

**Decision**: Remove all four `types-*` packages (`types-jsonschema`, `types-pyyaml`, `types-requests`, `types-toml`) alongside mypy.

**Rationale**: These packages provide type stubs for mypy. ty uses its own type inference and bundled stubs — it does not consume mypy-style stub packages. Removing them eliminates maintenance overhead.

**Risk**: If any non-mypy tool (e.g., IDE type checking in VSCode/Pylance) depends on these stubs, developers may lose type hints in their editors. Mitigation: ty's IDE integration (via ruff LSP) does not need these stubs.

## Decision 6: Suppressed Rule Baseline

**Current suppressed rules by module** (25 total rule-module pairs):

| Module | Rule | Count |
|--------|------|-------|
| tasks/ | unused-type-ignore-comment | 1 |
| tasks/ | invalid-argument-type | 1 |
| tasks/ | unresolved-attribute | 1 |
| backend/ | unused-type-ignore-comment | 1 |
| backend/ | invalid-argument-type | 1 |
| backend/ | invalid-assignment | 1 |
| backend/ | invalid-await | 1 |
| backend/ | invalid-method-override | 1 |
| backend/ | invalid-return-type | 1 |
| backend/ | invalid-type-arguments | 1 |
| backend/ | no-matching-overload | 1 |
| backend/ | not-subscriptable | 1 |
| backend/ | invalid-newtype | 1 |
| backend/ | invalid-type-form | 1 |
| backend/ | missing-argument | 1 |
| backend/ | unknown-argument | 1 |
| backend/ | unresolved-attribute | 1 |
| backend/ | unsupported-operator | 1 |
| cli/ | unresolved-attribute | 1 |
| driver/ | unused-type-ignore-comment | 1 |
| driver/ | unresolved-import | 1 |
| python_sdk/ | unused-type-ignore-comment | 1 |
| python_sdk/ | invalid-argument-type | 1 |
| python_sdk/ | invalid-assignment | 1 |
| python_sdk/ | invalid-type-form | 1 |

**Target**: Remove at least 13 of these 25 rule-module pairs (50%+).

**Expected easy wins**: All 4 `unused-type-ignore-comment` suppressions can be removed once mypy is gone and orphaned comments are cleaned up. That's already 4/25 = 16%.
