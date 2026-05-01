# Quickstart — Pre-Commit Hooks

This is the contributor-facing onboarding flow once this feature ships.

## First time on a fresh clone

```bash
# 1. Install Python and JS dependencies (existing prerequisite — not specific to this feature).
uv sync --all-groups --all-packages
cd frontend && pnpm install --frozen-lockfile && cd ..

# 2. Install the git hooks (this feature).
uv run invoke pre-commit-install
```

That's it. From the next commit onward, the configured checks will run automatically.

### Optional: install `prek` for faster local runs

```bash
# macOS / Linux — see https://github.com/j178/prek for the latest install command.
brew install j178/prek/prek         # macOS
curl -LsSf https://github.com/j178/prek/releases/latest/download/prek-installer.sh | sh   # Linux
```

If `prek` is on your `PATH`, the invoke tasks pick it up automatically. Nothing else changes.

## Day-to-day

```bash
git add ...
git commit -m "..."   # hooks fire automatically
```

Run all hooks against the whole repo manually:

```bash
uv run invoke pre-commit-run
```

## What runs when

- **On every `git commit`** (≤10 s on a warm cache): `ruff format --check`, `ruff check`, `ty check`, `yamllint`, `rumdl check`, `pnpm lint` (frontend changes only), `validate-graphql` (graphql changes only), `helm lint` (helm/ changes only), and standard hygiene hooks (trailing whitespace, EOF, merge markers, large files, private-key detection).
- **On every `git push`** (slower — these regenerate artefacts): GraphQL schema freshness, generated SDK + frontend type freshness.

If a hook fails, fix the issue, re-stage (`git add ...`), and re-commit.

## Bypassing hooks

For emergencies (network down, hook bug, hotfix to `develop` from automation that already validated):

```bash
git commit --no-verify -m "..."
```

Use sparingly. CI will still run all the per-tool jobs and fail the PR if anything is broken.

## Troubleshooting

- **"command not found: pnpm/helm/uv"** — install the missing tool. Pre-commit doesn't manage system tools; see the project's `AGENTS.md` for prerequisites.
- **Stale hook environment** (after a tool version bump):

  ```bash
  uv run pre-commit clean
  uv run invoke pre-commit-install
  ```

- **"works locally, fails in CI"** — usually a generated-file drift. Run `uv run invoke generate` and `uv run styrmin export graphql-schema schema.graphql`, commit the result, push.

## How to add a new hook

1. Edit `.pre-commit-config.yaml`.
2. Pin the `rev:` to a specific tag (no floating refs).
3. Choose the right stage:
   - Sub-second per change → `pre-commit` (default).
   - Multi-second / scans whole repo → `stages: [pre-push]`.
4. Add `files:` and/or `exclude:` patterns so the hook only runs where it makes sense.
5. Run `uv run invoke pre-commit-run` locally to confirm it works against the existing tree.
6. Open a PR — the CI `Pre-Commit Hooks` job validates the config end-to-end.
