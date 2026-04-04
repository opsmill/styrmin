# Feature Specification: Replace mypy with ty and Increase Type Checking Coverage

**Feature Branch**: `004-replace-mypy-with-ty`
**Created**: 2026-04-04
**Status**: Draft
**Input**: GitHub Issue #84 — Consolidate on ty as the sole type checker, removing mypy and progressively enabling suppressed ty rules.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Remove mypy from the Project (Priority: P1)

As a developer, I want to use a single type checker (ty) so that I don't have to maintain two sets of type-checking configurations, suppression comments, and stub packages. Removing mypy simplifies the toolchain and eliminates conflicts between the two tools.

**Why this priority**: This is the foundational change — all subsequent improvements depend on mypy being removed first. It unblocks enabling the `unused-type-ignore-comment` rule and cleaning up orphaned `# type: ignore` comments.

**Independent Test**: Can be fully tested by running the lint pipeline (`invoke lint`) and CI pipeline — both must pass with only ty as the type checker.

**Acceptance Scenarios**:

1. **Given** the project has mypy in dev dependencies, **When** mypy and all `types-*` stub packages are removed, **Then** `uv sync --all-groups` succeeds without mypy or stub packages installed.
2. **Given** `[tool.mypy]` and `[[tool.mypy.overrides]]` sections exist in `pyproject.toml`, **When** they are removed, **Then** no mypy configuration remains in the project.
3. **Given** the `lint_mypy` invoke task exists, **When** it is removed from `tasks/format.py` and `tasks/__init__.py`, **Then** `invoke lint` runs successfully without calling mypy.
4. **Given** the CI workflow includes `uv run mypy backend`, **When** that step is removed, **Then** CI passes with only the `uv run ty check` step for type checking.
5. **Given** `unused-type-ignore-comment` is suppressed per-module to coexist with mypy, **When** those suppressions are removed in ty config, **Then** `uv run ty check` identifies orphaned `# type: ignore` comments.
6. **Given** orphaned `# type: ignore` comments are identified, **When** they are removed, **Then** `uv run ty check` passes cleanly.

---

### User Story 2 - Increase ty Rule Coverage (Priority: P2)

As a developer, I want more ty rules enabled so that the type checker catches real bugs and type errors across the codebase, improving code quality and developer confidence.

**Why this priority**: With mypy removed, the focus shifts to getting more value from ty by enabling rules that were previously suppressed. This is incremental improvement — each rule can be enabled independently.

**Independent Test**: Can be tested by enabling a rule, running `ty check`, fixing violations, and verifying the check passes. Each rule enablement is an independent, testable unit.

**Acceptance Scenarios**:

1. **Given** suppressed ty rules exist across 5 modules, **When** each rule is audited, **Then** each is categorized as "fixable now", "upstream blocker", or "generated code".
2. **Given** a rule is categorized as "fixable now", **When** the underlying type errors are fixed, **Then** the rule can be removed from the ignore list and `ty check` passes.
3. **Given** a rule is categorized as "upstream blocker", **When** it cannot be fixed due to library limitations, **Then** the suppression is documented with a comment explaining the upstream issue.
4. **Given** a rule is categorized as "generated code", **When** it applies only to auto-generated files, **Then** the suppression remains with an explanatory comment.
5. **Given** the current state has ~25 suppressed rules across all modules, **When** fixable rules are resolved, **Then** at least 50% of the suppressed rules are removed.

---

### User Story 3 - Clean Developer Experience (Priority: P3)

As a developer, I want the project documentation and toolchain references to reflect the single-type-checker setup so that onboarding is straightforward and there is no confusion about which type checker to use.

**Why this priority**: Documentation consistency is important but lower priority than the functional changes. It ensures the benefits of consolidation are reflected in developer-facing materials.

**Independent Test**: Can be verified by reviewing AGENTS.md, CLAUDE.md, and any developer guides for references to mypy — none should remain except in historical context (ADRs).

**Acceptance Scenarios**:

1. **Given** AGENTS.md references mypy as a linting tool, **When** documentation is updated, **Then** only ty is listed as the type checker.
2. **Given** developer guides may reference mypy commands, **When** they are updated, **Then** all type-checking instructions reference ty only.

---

### Edge Cases

- What happens when a `# type: ignore` comment is needed by ty itself (not just mypy)? Those comments must be preserved.
- What happens when an enabled ty rule produces false positives on Strawberry GraphQL or SQLAlchemy patterns? Those rules should remain suppressed with documentation.
- What happens when generated code (e.g., `_generated/` directories) triggers ty errors? Generated code suppressions must remain untouched.
- What happens when `# type: ignore[specific-code]` comments exist that are mypy-specific error codes? They need to be evaluated — if ty doesn't recognize the error code, the comment becomes orphaned.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The project MUST NOT have mypy as a dependency after completion.
- **FR-002**: The project MUST NOT have any `types-*` stub packages (`types-jsonschema`, `types-pyyaml`, `types-requests`, `types-toml`) as dependencies after completion.
- **FR-003**: The `pyproject.toml` MUST NOT contain any `[tool.mypy]` or `[[tool.mypy.overrides]]` sections.
- **FR-004**: The invoke task `lint_mypy` MUST be removed from `tasks/format.py` and its invocation removed from `tasks/__init__.py`.
- **FR-005**: The CI workflow MUST NOT contain a mypy step.
- **FR-006**: The `unused-type-ignore-comment` rule MUST be enabled (no longer suppressed) in ty configuration.
- **FR-007**: All orphaned `# type: ignore` comments (those not needed by ty) MUST be removed.
- **FR-008**: `uv run ty check` MUST pass cleanly after all changes.
- **FR-009**: Each suppressed ty rule MUST be audited and categorized as fixable, upstream-blocked, or generated-code.
- **FR-010**: Fixable ty rules MUST be enabled and their underlying type errors resolved.
- **FR-011**: Upstream-blocked suppressions MUST be documented with comments explaining the reason.
- **FR-012**: The number of suppressed ty rules MUST be reduced by at least 50%.
- **FR-013**: Project documentation (AGENTS.md, CLAUDE.md) MUST be updated to reflect ty as the sole type checker.

### Assumptions

- ty version >=0.0.24 is sufficient for all required functionality.
- Some ty rules will remain suppressed due to upstream library limitations (Strawberry, SQLAlchemy, Pydantic) — this is expected and acceptable.
- Generated code in `_generated/` directories should not be manually modified; suppressions for generated code remain as-is.
- The `strawberry.ext.mypy_plugin` has no ty equivalent — any type narrowing provided by that plugin will not be available after migration.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Only one type checker (ty) runs in the lint pipeline and CI — no mypy references remain in configuration, tasks, or CI.
- **SC-002**: `uv run ty check` passes cleanly with zero errors on the entire project.
- **SC-003**: The number of suppressed ty rules across all modules is reduced by at least 50% from the current ~25 rules.
- **SC-004**: All remaining suppressed ty rules have documented justifications (upstream blocker or generated code).
- **SC-005**: The number of `# type: ignore` comments in the codebase is reduced (orphaned comments removed).
- **SC-006**: CI pipeline time for type checking is reduced by eliminating the duplicate mypy step.
