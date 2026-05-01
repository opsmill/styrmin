# Contract: `.pre-commit-config.yaml`

This is the configuration "contract" for the feature — the file shape that local runners (`prek`, `pre-commit`) and the CI job depend on. The pre-commit project owns the formal JSON schema upstream; this document records the **project-specific commitments** layered on top.

## Required top-level keys

```yaml
default_install_hook_types: [pre-commit, pre-push]
default_stages: [pre-commit]
exclude: |
  (?x)^(
    python_sdk/src/styrmin_sdk/graphql/_generated/.*
    | frontend/src/.*\.generated\.ts
    | .*/__pycache__/.*
    | pnpm-lock\.yaml
    | schema\.graphql
  )$
repos:
  - ...
```

The `exclude` regex MUST cover, at minimum, the paths listed in research R6. Adding more is allowed. Removing any of the listed paths requires updating this contract first.

## Required hook set (`pre-commit` stage)

The following hooks MUST be present in `.pre-commit-config.yaml` and assigned to the `pre-commit` stage (default):

| Hook id | Source | Files | Notes |
|---|---|---|---|
| `ruff-format` | `astral-sh/ruff-pre-commit` | `\.py$` | Runs `ruff format --check`. |
| `ruff-check` | `astral-sh/ruff-pre-commit` | `\.py$` | Runs `ruff check`. |
| `ty` | `local` | `\.py$` | `entry: uv run ty check`, `pass_filenames: false` (ty type-checks the project, not individual files). |
| `yamllint` | `adrienverge/yamllint` (or local `uv run yamllint`) | `\.(ya?ml)$` | Matches existing `.yamllint.yml`. |
| `rumdl` | `local` | `\.md$` | `entry: uv run rumdl check`. |
| `frontend-lint` | `local` | `^frontend/.*\.(ts|tsx|js|jsx|css)$` | `entry: pnpm --dir frontend lint`, `pass_filenames: false`. |
| `validate-graphql` | `local` | `\.graphql$` | `entry: uv run invoke validate-graphql`, `pass_filenames: false`. |
| `helm-lint-agent` | `local` | `^helm/agent/` | `entry: helm lint ./helm/agent`, `pass_filenames: false`. |
| `helm-lint-styrmin` | `local` | `^helm/styrmin/` | `entry: helm lint ./helm/styrmin`, `pass_filenames: false`. |
| `trailing-whitespace` | `pre-commit/pre-commit-hooks` | (default) | Hygiene. |
| `end-of-file-fixer` | `pre-commit/pre-commit-hooks` | (default) | Hygiene. |
| `check-merge-conflict` | `pre-commit/pre-commit-hooks` | (default) | Hygiene. |
| `check-added-large-files` | `pre-commit/pre-commit-hooks` | (default) | Hygiene; default 500 KB threshold. |
| `detect-private-key` | `pre-commit/pre-commit-hooks` | (default) | Cheap secrets baseline. |

## Required hook set (`pre-push` stage)

| Hook id | Source | Notes |
|---|---|---|
| `graphql-schema-freshness` | `local` | Runs `uv run styrmin export graphql-schema schema-check.graphql` and diffs against `schema.graphql`; fails if they differ. `stages: [pre-push]`. |
| `generated-types-freshness` | `local` | Runs `uv run invoke generate-validate` (already exists in `tasks/__init__.py`). `stages: [pre-push]`. |

## Pinning rules

- Every remote `repo:` entry MUST have a `rev:` set to a tagged release (no branches, no `HEAD`).
- The pinned versions are recorded inline in `.pre-commit-config.yaml`. Bumps go through normal PR review.

## CI invocation contract

The CI job in `.github/workflows/ci.yml` MUST install `prek` via `j178/setup-prek@v1` and invoke it via:

```text
prek run --all-files --show-diff-on-failure                            # pre-commit stage
prek run --hook-stage pre-push --all-files --show-diff-on-failure      # pre-push stage
```

It MUST cache `~/.cache/prek` keyed on `${{ hashFiles('.pre-commit-config.yaml', 'uv.lock', 'frontend/pnpm-lock.yaml') }}`.

## Invoke task contract

Two tasks are exposed under the project's existing `invoke` namespace:

- `uv run invoke pre-commit-install` — installs hooks for `pre-commit` and `pre-push` stages.
- `uv run invoke pre-commit-run` — runs all hooks against all files.

Both tasks MUST:

1. Shell out to `prek`.
2. If `prek` is not on PATH, exit non-zero with a clear pointer to the install instructions in `dev/guides/pre-commit-hooks.md`. No silent fallback.

## Backwards-compatibility commitments

- The hook config MUST use only standard `.pre-commit-config.yaml` syntax (no prek-only YAML extensions). This keeps the format portable in case the project ever revisits the runner choice.
