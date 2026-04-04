# ADR-003: Consolidate Type Checking on ty, Removing mypy

**Status**: Accepted
**Date**: 2026-04-04
**Source**: specs/archive/004-replace-mypy-with-ty/research.md (D1-D6)

## Context

The project ran two type checkers in parallel: mypy (checking only `backend/`) and ty (checking the entire project). This dual setup added CI time, cognitive overhead (two sets of suppression comments, two configurations), and maintenance cost (type stub packages, strawberry mypy plugin compatibility). The `unused-type-ignore-comment` rule in ty had to be globally suppressed to avoid conflicts with mypy's `# type: ignore` comments.

ty is developed by Astral (the same team behind ruff and uv), aligning with the project's existing toolchain. While ty is pre-1.0 and produces some false positives with Strawberry GraphQL and SQLAlchemy, it already provided broader coverage than mypy.

## Decision

Consolidate on ty as the sole type checker by:

1. Removing mypy, all `types-*` stub packages, and all mypy configuration
2. Removing the mypy CI step and invoke task
3. Enabling the `unused-type-ignore-comment` rule and cleaning orphaned comments
4. Auditing each suppressed ty rule per module and enabling those with fixable violations
5. Documenting remaining suppressed rules with upstream justification

## Consequences

**Easier:**

- Single type checker to configure, maintain, and understand
- No conflicting suppression comments between tools
- CI runs faster (one type check instead of two)
- Entire project is type-checked (not just `backend/`)
- Toolchain is fully Astral-aligned (ruff + ty + uv)

**Harder:**

- Some Strawberry/SQLAlchemy/Prefect patterns produce false positives in ty that mypy handled via its plugin system (`strawberry.ext.mypy_plugin` has no ty equivalent)
- Remaining suppressed rules (8 backend rule-module pairs) require periodic re-evaluation as ty matures
- IDE type checking may differ if developers use Pylance/Pyright instead of the ruff LSP

## Alternatives Considered

- **Keep both type checkers**: Rejected due to ongoing maintenance cost, suppression conflicts, and the fact that ty already covers the entire project while mypy only covers `backend/`.
- **Migrate to pyright**: Rejected because ty aligns with the existing Astral toolchain and is actively developed alongside ruff.
- **Remove all ty rule suppressions at once**: Rejected as impractical due to upstream false positives. The incremental approach (audit, categorize, fix or document) was more pragmatic.
