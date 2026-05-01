# Pre-Commit Hooks

This project enforces its mandatory lint, format, and validation checks locally via [pre-commit](https://pre-commit.com/) hooks. The same hook config is also enforced on every PR by the CI `Pre-Commit Hooks` job, so what runs on your machine matches what runs in CI.

## Why

Without local hooks, contributors regularly push commits that fail `ruff`, `yamllint`, `rumdl`, `pnpm lint`, or GraphQL validation, then wait several minutes for CI to round-trip the failure. The hooks catch those issues in seconds.

## Install

After cloning and running `uv sync --all-groups --all-packages` and `cd frontend && pnpm install`:

```bash
uv run invoke pre-commit-install
```

This installs git hooks for both the `pre-commit` and `pre-push` stages.

### Optional: install `prek` for faster runs

[`prek`](https://github.com/j178/prek) is a Rust-based drop-in reimplementation of `pre-commit`. It runs hooks in parallel and skips the per-hook Python virtualenv bootstrap, so local commits are noticeably faster.

```bash
brew install j178/prek/prek    # macOS
# or fetch the binary from https://github.com/j178/prek/releases
```

If `prek` is on `PATH`, the invoke tasks pick it up automatically. Nothing else changes — the same `.pre-commit-config.yaml` works for both runners.

## What runs and when

### On every `git commit` (pre-commit stage)

| Hook | What it does |
|---|---|
| `trailing-whitespace`, `end-of-file-fixer`, `check-merge-conflict`, `check-added-large-files`, `detect-private-key` | Standard hygiene. |
| `ruff format --check` | Python format check. |
| `ruff check` | Python lint. |
| `ty type-check` | Python type check (project's authoritative type checker). |
| `yamllint` | YAML lint, scoped to `*.yml` / `*.yaml`. |
| `rumdl check` | Markdown lint. |
| `frontend lint` | ESLint + Prettier on `frontend/**`. Only fires when frontend files change. |
| `validate-graphql` | Validates `.graphql` operations against `schema.graphql`. |
| `helm lint` | Lints `helm/agent` and `helm/styrmin`. Only fires when chart files change. |

These are sized to complete in well under 10 seconds combined on a warm cache.

### On every `git push` (pre-push stage)

| Hook | What it does |
|---|---|
| `GraphQL schema freshness` | Regenerates `schema.graphql` and diffs against the committed version. Fails if they differ. |
| `Generated SDK + frontend types freshness` | Regenerates the Pydantic SDK + frontend GraphQL types and fails if they differ from committed output. |

These are slower (they materialise generated artefacts), so they don't run on every commit. CI still runs the equivalent per-tool jobs even if you don't install the pre-push hook.

## Day-to-day

Run all hooks against the entire repo manually:

```bash
uv run invoke pre-commit-run
```

When a hook fails, fix the issue (most hooks tell you exactly what to change), `git add` the fix, and re-commit.

## Bypassing hooks

```bash
git commit --no-verify -m "..."
```

Acceptable use cases:

- **Network is down** and a hook genuinely needs network (rare; most hooks are local-only).
- **Hotfix from automation** to `develop`/`stable` that already ran the equivalent checks.
- **WIP personal-branch commits** that you'll squash before opening a PR.

Not acceptable: skipping hooks because "the lint failure is annoying". Fix it. CI's `Pre-Commit Hooks` job runs the same checks regardless and will fail your PR.

## Adding a new hook

1. Edit `.pre-commit-config.yaml`.
2. Pin the `rev:` to a specific tag (no floating refs like `HEAD` or branch names).
3. Pick the right stage:
   - **Sub-second on a typical change → `pre-commit`** (default).
   - **Multi-second / scans the whole repo → `stages: [pre-push]`**.
4. Scope with `files:` and/or `exclude:` so the hook only runs where it makes sense.
5. Run `uv run invoke pre-commit-run` locally to confirm it works against the existing tree.
6. Open a PR — the CI `Pre-Commit Hooks` job validates the config end-to-end.

## Troubleshooting

- **"command not found: pnpm/helm"** — install the missing system tool. Pre-commit doesn't manage system binaries; see the project's `AGENTS.md` for prerequisites.
- **Frontend lint fails with `eslint: command not found`** — run `cd frontend && pnpm install --frozen-lockfile` first.
- **`ty` reports unresolved imports for workspace packages** — run `uv sync --all-packages` (not just `uv sync`) so the workspace members are installed editably.
- **Stale hook environment after a tool version bump**:

  ```bash
  uv run pre-commit clean
  uv run invoke pre-commit-install
  ```

- **"works locally, fails in CI"** — usually a generated-file drift. Run `uv run invoke generate` and `uv run styrmin export graphql-schema schema.graphql`, commit the result, push.
- **Hook output is unclear** — run the hook in isolation with `uv run pre-commit run <hook-id> --all-files --verbose` to see the exact command and its full output.

## Reference

- Hook config: [`.pre-commit-config.yaml`](../../.pre-commit-config.yaml)
- Invoke wrappers: [`tasks/pre_commit.py`](../../tasks/pre_commit.py)
- CI job: `pre-commit-hooks` in [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)
- Spec: [`specs/006-prek-pre-commit-hooks/`](../../specs/006-prek-pre-commit-hooks/)
- Upstream docs: <https://pre-commit.com/> and <https://github.com/j178/prek>
