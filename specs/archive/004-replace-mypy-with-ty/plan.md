# Implementation Plan: Replace mypy with ty

**Branch**: `004-replace-mypy-with-ty` | **Date**: 2026-04-04 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/004-replace-mypy-with-ty/spec.md`

## Summary

Consolidate the project's type checking on ty (Astral's type checker) by removing mypy and its associated configuration, dependencies, and CI steps. Then progressively enable suppressed ty rules — fixing genuine type errors, documenting upstream blockers, and reducing the number of suppressed rules by at least 50%.

## Technical Context

**Language/Version**: Python 3.14+
**Primary Dependencies**: ty >=0.0.24, ruff (formatting/linting), uv (package manager), invoke (task runner)
**Storage**: N/A (no database changes)
**Testing**: pytest (verify type checker changes don't break existing tests)
**Target Platform**: Linux server (CI), macOS (developer machines)
**Project Type**: Web application (backend + frontend + SDK + CLI + driver)
**Performance Goals**: N/A (tooling change)
**Constraints**: Must not introduce new type errors; existing tests must continue to pass
**Scale/Scope**: ~165 `# type: ignore` comments across 53 files; 25 suppressed ty rule-module pairs across 5 modules

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Declarative State Reconciliation | N/A | No deployment logic changes |
| II. Driver-Based Deployment | N/A | No driver changes |
| III. Layered Architecture | N/A | No architectural changes |
| IV. Type Safety and Typed Errors | **REQUIRES UPDATE** | Constitution references mypy — must be updated to reference ty |
| V. Test-First Development | PASS | Existing tests must pass after changes |
| VI. Format and Lint Before Commit | PASS | `uv run invoke format lint` will still be required |

**Governance Gates Triggered**:
- **CI/CD workflow changes**: Removing mypy CI step (justified — replacing with existing ty step)
- **New dependencies**: None (ty already exists; removing mypy and stubs)

## Project Structure

### Documentation (this feature)

```text
specs/004-replace-mypy-with-ty/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── quickstart.md        # Phase 1 output
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
# Files to MODIFY:
pyproject.toml                    # Remove [tool.mypy], update [tool.ty], remove mypy deps
tasks/format.py                   # Remove lint_mypy task, register lint_ty
tasks/__init__.py                 # Remove lint_mypy invocation
.github/workflows/ci.yml          # Remove mypy CI step
AGENTS.md                         # Update linting references
.specify/memory/constitution.md   # Update Principle IV

# Files to MODIFY (type error fixes):
backend/**/*.py                   # Fix type errors, remove orphaned # type: ignore
python_sdk/**/*.py                # Fix type errors, remove orphaned # type: ignore
tasks/**/*.py                     # Fix type errors, remove orphaned # type: ignore
cli/**/*.py                       # Fix type errors if any
driver/**/*.py                    # Fix type errors, remove orphaned # type: ignore
```

**Structure Decision**: No new files or directories. This is purely modification of existing configuration, task definitions, CI pipeline, and source code type annotations.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Constitution Principle IV update | Must reflect new tooling reality | Cannot keep referencing mypy when it's removed |

## Implementation Phases

### Phase 1: Remove mypy (P1 — User Story 1)

**Goal**: Eliminate mypy from the project entirely.

1. **Remove mypy dependencies** from `pyproject.toml`:
   - Remove `mypy>=1.19.1` from `[dependency-groups] dev`
   - Remove `types-jsonschema`, `types-pyyaml`, `types-requests`, `types-toml`
2. **Remove mypy configuration** from `pyproject.toml`:
   - Delete `[tool.mypy]` section (lines 120-124)
   - Delete all `[[tool.mypy.overrides]]` sections (lines 125-148)
3. **Remove mypy invoke task**:
   - Delete `lint_mypy` function from `tasks/format.py`
   - Remove `ns.add_task(lint_mypy)` from `tasks/format.py`
   - Remove `fmt.lint_mypy(context)` call from `tasks/__init__.py`
   - Register `lint_ty` in collection: add `ns.add_task(lint_ty)` to `tasks/format.py`
4. **Remove mypy CI step**:
   - Delete the `uv run mypy backend` step from `.github/workflows/ci.yml`
5. **Enable `unused-type-ignore-comment`**:
   - Remove `unused-type-ignore-comment = "ignore"` from all ty overrides in `pyproject.toml`
   - Run `uv run ty check` to identify orphaned `# type: ignore` comments
   - Remove orphaned comments iteratively until `ty check` passes
6. **Verify**: `uv run ty check` passes cleanly, `uv run invoke lint` passes

### Phase 2: Increase ty Coverage (P2 — User Story 2)

**Goal**: Reduce suppressed ty rules by at least 50% (from 25 to <=12).

For each suppressed rule per module:
1. Temporarily enable the rule (remove from ignore list)
2. Run `uv run ty check` to see violations
3. Categorize: fixable / upstream blocker / generated code
4. If fixable: fix the type errors and keep the rule enabled
5. If upstream blocker: re-suppress with documentation comment
6. If generated code: re-suppress with documentation comment

**Priority order** (smallest violation count first for quick wins):
- cli/ rules (1 rule)
- driver/ rules (1 remaining after `unused-type-ignore-comment` removed)
- tasks/ rules (2 remaining)
- python_sdk/ rules (3 remaining)
- backend/ rules (14 remaining — tackle easiest first)

### Phase 3: Documentation Updates (P3 — User Story 3)

1. Update `AGENTS.md` — change linting line from "ruff, mypy (backend)" to "ruff, ty"
2. Update `.specify/memory/constitution.md` Principle IV — reference ty instead of mypy
3. Update any dev guides that mention mypy
