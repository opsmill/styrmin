# Quickstart: Replace mypy with ty

## What Changed

This feature consolidates the project's type checking from dual-checker (mypy + ty) to ty-only. After implementation:

- `uv run invoke lint` runs ty (not mypy) for type checking
- `uv run ty check` is the sole type-checking command
- mypy, type stub packages, and mypy configuration are removed
- Orphaned `# type: ignore` comments are cleaned up
- More ty rules are enabled with stricter type checking

## Developer Impact

### Before

```bash
uv run invoke lint   # runs: ruff, ty, mypy, markdown, yaml
uv run mypy backend  # standalone mypy check
```

### After

```bash
uv run invoke lint   # runs: ruff, ty, markdown, yaml (no mypy)
uv run ty check      # standalone type check (whole project)
uv run invoke lint-ty  # standalone ty via invoke
```

## Suppression Comments

- **Before**: `# type: ignore` comments were needed for mypy; `unused-type-ignore-comment` was suppressed in ty config to avoid conflicts.
- **After**: Only `# type: ignore` comments needed by ty remain. If you need to suppress a ty error, use `# type: ignore[rule-name]` with the specific ty rule.

## Adding New Type Suppressions

If you encounter a ty false positive:

1. Use specific rule suppression: `# type: ignore[invalid-argument-type]`
2. Add a comment explaining why: `# type: ignore[invalid-argument-type]  # Strawberry resolver signature`
3. If a rule produces widespread false positives, consider adding it to the module's `[tool.ty.overrides.rules]` in `pyproject.toml`
