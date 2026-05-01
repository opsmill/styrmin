# Phase 1 — Data Model

This feature introduces no runtime data. The "entities" below describe the **declarative structures** that ship with the feature, captured here so reviewers can see at a glance what is being added or modified and how the parts connect.

## E1. Hook config (`.pre-commit-config.yaml`)

A YAML document at the repo root, conforming to the [pre-commit config schema](https://pre-commit.com/#pre-commit-configyaml---top-level), defining:

| Field | Type | Required | Notes |
|---|---|---|---|
| `default_install_hook_types` | list of strings | yes | `[pre-commit, pre-push]` so a single `install` covers both stages. |
| `default_stages` | list of strings | yes | `[pre-commit]` — slow hooks override individually. |
| `exclude` | regex | yes | Top-level exclude covering generated dirs (see research R6). |
| `repos` | list of repo entries | yes | Each entry is either `repo: local` or a remote repo at a pinned tag. |

Each `repos[]` entry contains:

| Field | Type | Required | Notes |
|---|---|---|---|
| `repo` | string | yes | URL or `local`. |
| `rev` | string | yes (when `repo != local`) | Pinned tag (e.g., `v0.7.4`). |
| `hooks` | list of hook entries | yes | At least one. |

Each `hook` entry contains:

| Field | Type | Required | Notes |
|---|---|---|---|
| `id` | string | yes | Hook identifier. For `local` repos this is a project-defined name; for remote repos it must match the upstream id. |
| `name` | string | recommended | Human-friendly name shown in output. |
| `language` | string | required for `local` | `system` for CLI shell-outs; `python` for `uv run`-style; `node` for pnpm; etc. |
| `entry` | string | required for `local` | Command to execute. |
| `files` | regex | optional | Restricts which paths trigger the hook. |
| `exclude` | regex | optional | Per-hook excludes layered on top of the global exclude. |
| `pass_filenames` | bool | optional | When `false`, the hook receives no filename args (used for project-wide checks like `validate-graphql`). |
| `stages` | list of strings | optional | Defaults to `default_stages`; slow hooks override to `[pre-push]`. |
| `args` | list of strings | optional | Additional CLI flags. |

**Validation rules**:

- Every `local` hook MUST set both `language` and `entry`.
- Every remote `repo` MUST set `rev` to a tagged release (no branch refs).
- Every hook that runs against a Python tool installed via `uv` MUST use `language: system` and prefix `entry` with `uv run` so contributors don't need a parallel virtualenv.
- The top-level `exclude` MUST cover at minimum the generated paths listed in research R6.

## E2. Invoke task module (`tasks/pre_commit.py`)

A new Python module with two `@task` entries, registered in `tasks/__init__.py`:

| Task | Purpose | Behaviour |
|---|---|---|
| `pre-commit-install` | Install git hooks for `pre-commit` and `pre-push` stages. | Shells out to `prek install` (which honours `default_install_hook_types` from the YAML). If `prek` is not on PATH, exit non-zero with a pointer to the install instructions. |
| `pre-commit-run` | Run all hooks against the entire repo. | Shells out to `prek run --all-files`. Same `prek`-required failure path. |

**Type contract**: Both functions accept `(context: Context)` and return `None`. They use `# noqa: ARG001` because they don't read `context` directly — they shell out via the project's `print_header`/`context.run` helpers, matching `tasks/format.py`.

## E3. CI workflow job (`pre-commit-hooks` job in `.github/workflows/ci.yml`)

A new job alongside the existing per-tool jobs:

| Property | Value |
|---|---|
| `name` | `Pre-Commit Hooks` |
| `runs-on` | `ubuntu-latest` |
| `timeout-minutes` | `10` (covers cold-cache install + run) |
| `steps` | 1) checkout, 2) setup Python 3.14 + uv + `uv sync --all-packages` (so the local hooks shelling out via `uv run` find their tools), 3) setup pnpm + Node + `pnpm install` in `frontend/` (for `frontend-lint`), 4) setup Helm (for `helm-lint-*`), 5) install `prek` via `j178/setup-prek@v1`, 6) restore `~/.cache/prek` cache keyed on `.pre-commit-config.yaml` + `uv.lock` + `frontend/pnpm-lock.yaml`, 7) `prek run --all-files --show-diff-on-failure`, 8) `prek run --hook-stage pre-push --all-files --show-diff-on-failure`, 9) save cache. |

The job runs on every `pull_request` and on `push` to `develop` (matches the existing CI triggers).

## E4. AGENTS.md additions

A new bullet under "Always Do" instructing contributors to run the install task once after cloning, plus a small contributor-facing note (≤10 lines) on the bypass policy.

## E5. Dev guide (`dev/guides/pre-commit-hooks.md`)

A standalone contributor-facing reference covering:

1. Why the hooks exist (link to spec).
2. How to install (`uv run invoke pre-commit-install`, optionally `prek install`).
3. Which checks run on `pre-commit` vs `pre-push`, with timing guidance.
4. How to bypass (`git commit --no-verify`) and when it's appropriate.
5. How to add a new hook (file pointer to `.pre-commit-config.yaml`, naming conventions, how to choose the right stage).
6. Troubleshooting (cache-corruption recovery, `pre-commit clean`, version mismatch between local and CI).

## Relationships

```text
.pre-commit-config.yaml  <-- single source of truth
   │
   ├── consumed by:  prek (the only supported runner)
   │
   ├── invoked by:   tasks/pre_commit.py  ───► uv run invoke pre-commit-{install,run}
   │
   └── enforced by:  .github/workflows/ci.yml ::pre-commit-hooks job (prek run --all-files, both stages)

AGENTS.md (Always Do)  ───►  points contributors to dev/guides/pre-commit-hooks.md
```
