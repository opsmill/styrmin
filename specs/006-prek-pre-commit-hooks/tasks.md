# Tasks: Pre-Commit Hooks via prek

**Input**: Design documents from `specs/006-prek-pre-commit-hooks/`
**Prerequisites**: spec.md, plan.md, research.md, data-model.md, contracts/pre-commit-config.schema.md, quickstart.md

**Organization**: Tasks are grouped by user story so each story can be shipped independently if needed. Stories US1 (local enforcement) and US2 (prek/pre-commit parity) are both P1 and share the same hook config — they are jointly delivered by Phase 3.

## Format

`[ID] [P?] [Story] Description`

- `[P]` — can run in parallel with other `[P]` tasks (different files, no shared state)
- `[Story]` — `US1`–`US5` from spec.md, or `Setup`/`Final` for shared work

---

## Phase 1: Setup (shared infrastructure)

- [ ] **T001** Confirm `prek` is installable on developer machines and the CI runner. The chosen install paths are: `brew install j178/prek/prek` on macOS, the upstream installer script on Linux, and the `j178/setup-prek@v1` GitHub Action on CI.

---

## Phase 2: Foundational — hook config

**Goal**: Land the canonical `.pre-commit-config.yaml` so every later task has a config to register against.

- [ ] **T002** [Setup] Create `.pre-commit-config.yaml` at the repo root following the contract in `specs/006-prek-pre-commit-hooks/contracts/pre-commit-config.schema.md`. Include all hooks marked for the `pre-commit` stage *and* the slow hooks for the `pre-push` stage. Pin every remote `repo:` to a tagged release. Set the top-level `exclude:` regex per research R6. The config must parse cleanly with `prek run --all-files` (parse errors are surfaced as runtime errors).

**Checkpoint**: A contributor can run `prek run --all-files` against the existing tree and the config parses (failures from the actual checks at this point are expected and fine — they prove the hooks resolve).

---

## Phase 3: User Story 1 — local enforcement via prek (P1) 🎯 MVP

**Goal**: A contributor can install `prek`, install the hooks, and have every mandatory check fire before each commit.

**Independent test**: From a fresh clone, install prek, run the invoke install task, introduce a `ruff format` violation in a Python file, attempt `git commit`, observe the hook block the commit. Repeat with the markdown linter and the YAML linter.

- [ ] **T003** [US1] Create `tasks/pre_commit.py` with two `@task` functions: `pre_commit_install` (registered as `pre-commit-install`) and `pre_commit_run` (registered as `pre-commit-run`). Each uses a small helper `_ensure_prek()` that raises `SystemExit` with install instructions if `prek` is not on PATH. The functions then shell out to `prek install` / `prek run --all-files --show-diff-on-failure`. Annotate types per the project's invoke style.
- [ ] **T004** [US1] Register the two new tasks in `tasks/__init__.py` (`ns.add_task(pre_commit.pre_commit_install)` and `ns.add_task(pre_commit.pre_commit_run)`). Confirm they show up in `uv run invoke --list`.
- [ ] **T005** [US1] Run `uv run invoke pre-commit-install` against the local clone. Verify `.git/hooks/pre-commit` and `.git/hooks/pre-push` are created and executable.
- [ ] **T006** [US1] Run `uv run invoke pre-commit-run` against the whole repo. **Fix every legitimate violation it surfaces** — this is the "pay the migration cost once" step. For violations that are spurious (e.g., generated files we forgot to exclude), update the `exclude:` regex in `.pre-commit-config.yaml` instead of fixing the file. End state: `prek run --all-files` exits 0.

**Checkpoint**: Local enforcement works end-to-end with prek.

---

## Phase 4: User Story 3 — CI parity job (P2)

**Goal**: A new CI job runs the hooks on every PR so the config is enforced and stays aligned with the per-tool jobs.

**Independent test**: Push a branch with a deliberate `ruff format` violation. Confirm the new `Pre-Commit Hooks` job fails on the PR with the same hook output a contributor would have seen locally. Push a fix; confirm the job goes green.

- [ ] **T008** [US3] Add a `pre-commit-hooks` job to `.github/workflows/ci.yml`. It checks out the repo, sets up Python 3.14, installs `uv`, runs `uv sync --all-packages`, sets up pnpm/Node, runs `pnpm install --frozen-lockfile` in `frontend/`, sets up Helm, installs prek via `j178/setup-prek@v1`, restores `~/.cache/prek` cached on `${{ hashFiles('.pre-commit-config.yaml', 'uv.lock', 'frontend/pnpm-lock.yaml') }}`, runs `prek run --all-files --show-diff-on-failure` for the `pre-commit` stage, and runs `prek run --hook-stage pre-push --all-files --show-diff-on-failure` for the pre-push stage. Triggers must match the existing CI workflow (PR + push to `develop`). Set `timeout-minutes: 10`. Do **not** remove or modify the existing per-tool jobs — they stay in place per spec FR-013.
- [ ] **T009** [US3] Add the new job to the `needs:` list of any downstream job that should wait on lint signal (mirroring how the existing per-tool jobs gate `frontend-test`, etc.) **only if** doing so does not change which jobs run in parallel meaningfully. If unsure, leave `needs:` alone and rely on the new job running independently. Document the choice inline in the workflow.
- [ ] **T010** [US3] Open a sacrificial commit on this branch with one deliberate violation, push, observe CI catch it, then revert the violation. Capture a screenshot or short note of the failing job in the PR description so reviewers can see the new check working.

---

## Phase 5: User Story 4 — onboarding via invoke (P2)

**Goal**: A new contributor can become "compliance-ready" with one documented command after `uv sync`.

**Independent test**: On a fresh clone (or `git stash` + `rm -rf .git/hooks/pre-commit`), run `uv run invoke pre-commit-install`. Verify a subsequent `git commit` invokes the hooks.

- [ ] **T011** [US4] Update `AGENTS.md` "Always Do" section: add a bullet "Install the pre-commit hooks once after cloning: `uv run invoke pre-commit-install`." Place it near the existing "Run formatters before committing" bullet, since the hook now provides that enforcement.
- [ ] **T012** [US4] Add a small "Bypassing hooks" subsection to `AGENTS.md` (≤10 lines) explaining `git commit --no-verify` and the acceptable use cases per research R8. Link to `dev/guides/pre-commit-hooks.md` for full detail.
- [ ] **T013** [P] [US4] Create `dev/guides/pre-commit-hooks.md` based on the structure outlined in `data-model.md` §E5: why, install, what runs when, bypassing, adding new hooks, troubleshooting. Use the content from `specs/006-prek-pre-commit-hooks/quickstart.md` as the seed and expand the troubleshooting section with the specific failure modes we hit during T006.

---

## Phase 6: User Story 5 — slow hooks gated to pre-push (P3)

**Goal**: Slow checks run on `git push`, not on every commit, so per-commit latency stays under 10 s.

**Independent test**: Make a change to a `.graphql` file. Confirm `git commit` runs the lightweight `validate-graphql` hook (sub-second) but **not** the schema-freshness hook. Run `git push` (or `prek run --hook-stage pre-push --all-files`) and confirm the schema-freshness hook fires and blocks if generated artefacts are stale.

> **Note**: T002 already includes the slow hooks under `stages: [pre-push]`. The work here is to **verify** the gating actually behaves correctly. If it doesn't, this phase loops back to T002.

- [ ] **T014** [US5] Verify that `prek run --all-files` (default = `pre-commit` stage) does **not** invoke `graphql-schema-freshness` or `generated-types-freshness`. Confirm with `--verbose` output.
- [ ] **T015** [US5] Verify that `prek run --hook-stage pre-push --all-files` **does** invoke both slow hooks. Confirm they pass on the current `develop`-aligned tree (otherwise the tree itself is broken — fix that first via `uv run invoke generate` and `uv run styrmin export graphql-schema schema.graphql`).
- [ ] **T016** [US5] Time a representative `git commit` on a small change (e.g., touching one Python file plus one Markdown file) on a warm cache. Record the wall-clock time in the implementation notes. Target: ≤10 s per spec SC-003. If exceeded, either move more hooks to `pre-push` or scope the offending hook to specific files only.

---

## Phase 7: Final — verification and polish

- [ ] **T017** Run `uv run invoke format lint` (existing repo command) and confirm clean. This is the project's mandatory pre-commit check per constitution §VI.
- [ ] **T018** Run `prek run --all-files` one final time on the prepared branch and confirm exit 0.
- [ ] **T019** Manually verify the spec's success criteria as far as is possible at PR time:
  - SC-002: time the install command on a freshly-cloned worktree.
  - SC-003: time a clean commit (already done in T016).
  - The percentage-based criteria (SC-001, SC-004, SC-005) are post-merge observation criteria; note this in the PR description so the team knows to monitor.

---

## Dependencies

```text
T001 ──► T002 ──► T003 ──► T004 ──► T005 ──► T006 ──► T007
                                              │
                                              ├──► T008 ──► T009 ──► T010
                                              │
                                              ├──► T011 ──► T012  T013(P)
                                              │
                                              └──► T014 ──► T015 ──► T016 ──► T017 ──► T018 ──► T019
```

T006 is the critical "fix the existing tree" step — every later phase depends on it producing a clean tree. T013 can run in parallel with T011/T012 since it touches a different file.

## Parallelism notes

- T013 (`dev/guides/pre-commit-hooks.md`) is `[P]` against T011/T012 (`AGENTS.md`) — different files.
- Most other tasks are sequential because they share `.pre-commit-config.yaml` or depend on the previous task's output.
