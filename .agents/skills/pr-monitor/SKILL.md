---
name: pr-monitor
description: Monitor an existing pull request's CI in a loop; when a job fails, reproduce locally, fix it, push, and retry up to 5 times — reverting all fix attempts if no green run is reached.
argument-hint: Optional PR number or URL (defaults to the PR for the current branch)
compatibility: Requires a Git working tree, GitHub access (gh CLI authenticated), and the Styrmin repo layout (uv, pnpm, vcluster, kubectl) for local reproduction.
metadata:
  source: User-requested CI babysitter skill
---

# Pull Request CI Monitor

## Introduction

Watch the CI for a pull request, and when something fails, fix it the careful way: reproduce the failure locally before changing anything, validate the fix locally before pushing, and retry up to 5 times. If 5 fix attempts still leave the PR red, revert every fix-attempt commit and hand back the PR in its original state — five failed attempts is a strong signal the changes are misguided.

Push-without-local-reproduction is allowed **only** when the failure cannot be reproduced locally (genuine CI-only divergence). Never push a speculative fix when local reproduction is possible.

## Execution Mode

This skill is designed to run as a **background survey agent**, not in the user's foreground turn. CI on this repo runs for tens of minutes (E2E jobs alone cap at 45 min each), and a fix-and-retry loop multiplies that by up to 5 iterations. Blocking the parent conversation that long is wasteful — spawn this skill as an asynchronous agent and let it report back when it has something to say.

- **Recommended invocation:** by another skill (notably `/pr` Phase 7) using the runtime's background-agent primitive (Claude Code: `Agent` with `run_in_background: true`; equivalent in other runtimes).
- **Acceptable invocation:** directly by the user as `/pr-monitor` when they explicitly want to watch a PR. In that case the loop runs in the foreground and the user can interrupt.
- The skill is **self-contained**: it captures `baseline_commit` itself in Phase 0 and resolves the PR/branch from arguments or current branch. No state needs to be inherited from the spawning conversation beyond what is passed in `$ARGUMENTS`.

## Arguments

<arguments> $ARGUMENTS </arguments>

**Supported arguments:**

- _(no args)_ — Use the PR for the current branch.
- `<PR-number>` — Use the PR with that number on the current repo.
- `<PR-URL>` — Use the PR at that GitHub URL.

---

## State

Maintain these variables throughout the run. Track them in your scratch space; they drive the retry/revert logic.

```text
iteration            = 0
max_iterations       = 5
pr_number            = <resolved in Phase 0>
branch               = <resolved in Phase 0>
baseline_commit      = <HEAD on the branch when the skill starts — the revert target>
fix_commits          = []     # SHAs created by this skill while attempting fixes
ci_resolved          = false
attempt_log          = []     # One entry per iteration
```

Every fix attempt produces exactly one new commit on the branch, appended to `fix_commits`. This is what makes the Phase 6 revert deterministic.

---

## Phase 0: Resolve Target PR & Baseline

1. **Verify the working directory is the repo root:**

   ```bash
   cd "$(git rev-parse --show-toplevel)"
   test -f CLAUDE.md && test -d backend && test -d frontend
   ```

   If the assertion fails, STOP — not in the Styrmin repo.

2. **Resolve the PR.** Determine `pr_number` and `branch`:

   - If `$ARGUMENTS` looks like a number → `pr_number = $ARGUMENTS`.
   - If `$ARGUMENTS` looks like a URL → extract the number with `gh pr view "$ARGUMENTS" --json number -q .number`.
   - Otherwise → `pr_number = $(gh pr view --json number -q .number)` for the current branch. If no PR exists, STOP and tell the user to open one (or run `/pr` first).

   Then capture metadata:

   ```bash
   gh pr view <pr_number> --json number,headRefName,headRefOid,baseRefName,state,isDraft,mergeable,statusCheckRollup
   ```

   - `branch        = headRefName`
   - `baseline_oid  = headRefOid`  (used for safety checks; the local revert target below is what matters)

3. **Check out the PR branch locally** (if not already):

   ```bash
   git fetch origin
   git checkout <branch>
   git pull --ff-only origin <branch>
   ```

   If `git pull` is not fast-forward, STOP and tell the user the local branch has diverged from origin — they need to reconcile first.

4. **Record `baseline_commit`** as the current HEAD. This is the **local revert target** if all 5 iterations fail:

   ```bash
   baseline_commit=$(git rev-parse HEAD)
   ```

   Verify it matches `headRefOid` from step 2. If they differ, STOP — the branch is out of sync with the PR head and any revert would lose work.

5. **Refuse to operate on protected branches:** if `branch` is `develop` or `main`, STOP. This skill is for feature PRs only.

6. **Report to the user:** PR number, title, branch, baseline commit short SHA, current statusCheckRollup summary (counts of pending/success/failure). Then proceed.

---

## Phase 1: Monitor CI

The goal of this phase is to discover whether the CI is currently passing, failing, or still running — and to wait through "still running" states.

1. **Find the most recent CI run for the branch:**

   ```bash
   gh run list --branch <branch> --limit 10 --json databaseId,name,status,conclusion,event,headSha,createdAt
   ```

   Filter to runs whose `headSha` matches the current branch tip. If multiple workflows ran for the same SHA (e.g., `CI`, `claude`, `docker-publish`), look at all of them — the PR is only green if every required check is green.

2. **Wait for in-flight runs to settle.** While any run for the current SHA has `status` other than `completed`:

   - Poll every 60 seconds: `gh run list --branch <branch> --limit 10 --json databaseId,status,conclusion,headSha`.
   - Be patient — CI for this repo can take 30+ minutes (E2E jobs run on huge-runners, ~45 min timeout each).
   - If nothing has appeared after 5 minutes from a fresh push, investigate whether the push triggered a workflow at all (`gh run list --branch <branch> --limit 5`). Stalled webhooks happen.

3. **Once all runs for the SHA are `completed`:**

   - If every run's `conclusion == success` (or `skipped` for legitimately skipped jobs) → set `ci_resolved = true`, go to Phase 5.
   - If any `conclusion in {failure, cancelled, timed_out, action_required}` → go to Phase 2.

4. **If `iteration == 0` and CI is already green** when the skill is first invoked: report this to the user and exit cleanly. Nothing to do.

---

## Phase 2: Classify Failures

For each failed run, list its failed jobs and decide which reproduction track each falls under.

1. **List failed jobs for each failed run:**

   ```bash
   gh run view <run-id> --json jobs --jq '.jobs[] | select(.conclusion=="failure") | {name, databaseId, conclusion}'
   ```

2. **Classify each failed job by name** (defined in `.github/workflows/ci.yml`):

   | Job name | Track | Local reproduction command |
   |---|---|---|
   | `Pre-Commit Hooks` | **lint** | `uv run invoke format lint` (and re-run failing pre-commit hooks: `prek run --all-files` / `prek run --hook-stage pre-push --all-files`) |
   | `Frontend Tests` | **frontend-test** | `cd frontend && pnpm test` |
   | `Frontend Build` | **frontend-build** | `cd frontend && pnpm build` |
   | `Unit Tests` | **unit** | The exact pytest invocation from the workflow (see step 3) |
   | `E2E Tests (API entrypoint)` | **e2e** | Delegate to `/e2e-troubleshoot` for the failing test (see Phase 3.e2e) |
   | `E2E Tests (UI entrypoint)` | **e2e** | Delegate to `/e2e-troubleshoot` for the failing test (see Phase 3.e2e) |
   | Anything else | **other** | Read logs and ask the user before guessing |

3. **Pull the failing log lines** for every failed job. Don't dump the whole log; extract the failing test/check:

   ```bash
   gh run view <run-id> --log-failed > /tmp/pr-monitor-failed-<run-id>.log
   ```

   For pytest jobs, grep for `FAILED ` and `ERROR ` lines — those give the node IDs to reproduce. For lint jobs, find the hook name and the specific file/rule it complained about. For frontend tests, capture the failing test file path and the specific `it`/`describe` name.

4. **Always reproduce as narrowly as possible.** The goal is the smallest local invocation that exercises the failing case, not a full-suite re-run. A pytest run that targets one node ID finishes in seconds; a full unit suite takes minutes; a full E2E suite takes 30+ minutes. Narrow runs are also clearer to debug — less noise in the output. Concretely:

   - Pull the **exact** failing node IDs / file paths / hook names from the log first. Don't fall back to a broad suite while there are specific names to try.
   - If the first narrow command fails to reproduce or the node ID was wrong (typo, parametrized name not matched), try a slightly broader form — for pytest, drop the parameter suffix or step up to the file; for vitest, step up to the file. **Widen one notch at a time**, never jump straight to the full suite.
   - Only fall back to the full-suite invocation as a last resort, and only after at least two narrowed attempts didn't pinpoint it. Note the fallback explicitly in `attempt_log`.
   - Once the fix is in, re-run the narrow command first to confirm the fix; you may then run the broader suite as a regression check before pushing — but keep the **reproduction** step narrow.

5. **Decide the order of attack.** Fix one failure per iteration. Prefer the cheapest one first (lint < frontend-test < unit < e2e), because lint failures often mask deeper issues and are fast to fix. Record the chosen target in `attempt_log` for this iteration:

   ```text
   attempt_log[iteration] = {
       failing_jobs: [<list of job names that failed>],
       target_job:   <the one being fixed this iteration>,
       target_node:  <test node id or hook name being reproduced>,
       failure_excerpt: <a few key log lines>,
   }
   ```

---

## Phase 3: Reproduce Locally and Fix

**Hard rule:** never push a speculative fix when local reproduction is possible. Reproduce first, then fix, then re-verify locally, then push.

The reproduction strategy depends on the track. Pick the matching subsection.

### 3.lint — Pre-Commit Hooks

Narrow first: run only the hook(s) that failed, on only the file(s) they flagged.

1. From the failed-job log, identify the specific hook id (e.g., `ruff`, `ty`, `prettier`, `eslint`, `yamllint`) and the file paths it complained about.
2. Reproduce that hook in isolation against just those files:

   ```bash
   prek run <hook-id> --files <file1> <file2>
   ```

3. If the narrow run doesn't reproduce, widen one notch — run the same hook on all files:

   ```bash
   prek run <hook-id> --all-files --show-diff-on-failure
   ```

4. Only as a last resort, run the full pre-commit + pre-push gate that CI runs:

   ```bash
   uv run invoke format lint
   prek run --all-files --show-diff-on-failure
   prek run --hook-stage pre-push --all-files --show-diff-on-failure
   ```

5. If the failure reproduces:
   - Read the failing rule/file.
   - Apply the minimal fix — formatter auto-fixes are fine; for type errors, fix the actual type.
   - Re-run the **same narrow command** to confirm. Then run the full gate once before pushing as a regression check.
6. If the failure does **not** reproduce even at the broadest local invocation (rare for lint, but possible — version drift, OS-specific): document this in `attempt_log` and proceed to Phase 4 with a best-effort fix. Note the unreproduced status.

### 3.unit — Unit Tests

Narrow first: run only the failing test node(s), not the full suite. A single-node run takes seconds; the full unit suite takes minutes — don't pay that cost while diagnosing.

1. Identify the **exact** failing pytest node IDs from the log (Phase 2 step 3 — grep for `FAILED ` / `ERROR ` lines).
2. Reproduce one node at a time:

   ```bash
   uv run pytest -v <full_node_id>
   ```

   Run multiple failing nodes in a single invocation if there's more than one — still narrower than the full suite:

   ```bash
   uv run pytest -v <node_id_1> <node_id_2> <node_id_3>
   ```

3. If a node ID doesn't match (typo, parametrized id mismatch, file moved), widen **one notch at a time**:
   - First, drop the parameter suffix (e.g., `test_foo[case1]` → `test_foo`).
   - Then, fall back to the file: `uv run pytest -v <path/to/test_file.py>`.
   - Then, the directory: `uv run pytest -v backend/tests/unit/<subdir>`.
   - Do **not** jump straight to the full suite.
4. **Only as a last resort**, after at least two narrowed attempts have failed to pinpoint the failure, re-run the full unit suite the way CI does:

   ```bash
   uv run pytest -v \
     --ignore=backend/tests/e2e \
     --ignore=backend/tests/integration \
     --deselect=backend/tests/unit/test_styrmin_deployment_timer.py::test_timer_still_trips_timeout_for_non_restoring_phase \
     backend/tests
   ```

   Note in `attempt_log` that you fell back to the full suite and why.
5. If it reproduces:
   - Read the traceback. Read the test. Read the code under test.
   - Apply the minimal fix — fix the code if the test asserts the right behavior; fix the test if the test is wrong. Be sure which is which before changing either.
   - Re-run the **same narrow command** until it passes. Then run the broader suite once before pushing as a regression check (but only if the narrow fix landed cleanly).
6. If it does **not** reproduce locally even at the narrow level: gather environment evidence (Python version, dependency versions, `uv.lock` diff vs. CI), document, and proceed to Phase 4 with a tentative fix. CI-only failures justify a push without local repro.

### 3.frontend-test / 3.frontend-build

Narrow first for frontend tests too: vitest accepts a file path and a `-t` filter, so target the specific failing case rather than the whole suite.

1. From the failed-job log, capture the failing test file and the `it`/`describe` name (vitest reports both).
2. Reproduce **just** that test:

   ```bash
   cd frontend
   pnpm install --frozen-lockfile      # only if dependencies look out of sync
   pnpm test <relative/path/to/file.test.tsx> -t "<test name fragment>"
   ```

3. If the narrow form doesn't match (test name renamed, escaping issues), widen one notch:
   - Drop the `-t` filter and run the whole file: `pnpm test <path/to/file.test.tsx>`.
   - Then a parent directory.
   - Only as a last resort, run `pnpm test` with no arguments. Note the fallback in `attempt_log`.
4. For `frontend-build` failures, `pnpm build` runs `tsc` — type errors land there. The build is already a single command; the narrowing instinct still applies to the **fix**: change only the file that produced the type error, not the surrounding module.
5. If it reproduces, fix it the same way (minimal, scoped). Re-run the narrow `pnpm test ... -t ...` invocation to confirm. Run the full `pnpm test` / `pnpm build` once before pushing as a regression check.
6. If it does **not** reproduce: document and proceed.

### 3.e2e — E2E Tests

E2E failures are the most expensive to reproduce locally (vcluster spin-up, several minutes per run, ~30+ minutes for the full suite). **Never reproduce by running the whole `backend/tests/e2e` directory.** Always target the specific failing test. Use the dedicated troubleshooter rather than re-implementing the loop here.

1. Identify the **specific** failing test node ID from the failed-job log — grep for `FAILED backend/tests/e2e/...` lines. The node ID looks like `backend/tests/e2e/test_deploy_app.py::test_deploy_simple_app[api-chromium]` (the `[api-chromium]` / `[ui-chromium]` suffix tells you which entrypoint variant failed; preserve it when delegating).
2. If multiple E2E tests failed in CI, pick **one** to focus this iteration on — typically the first one to fail, or the one whose failure mode is clearest. Don't try to debug several E2E tests in parallel.
3. Delegate to the `/e2e-troubleshoot` skill with that single node ID. It targets exactly that node with `--pdb` and does its own internal up-to-5 iteration loop with kubectl introspection and fix application. **Treat its entire outcome as a single iteration of `pr-monitor`** — even though it has its own internal retries.
4. If `/e2e-troubleshoot` reports FIXED with a local pass, the fix is applied to the working tree; proceed to Phase 4.
5. If `/e2e-troubleshoot` reports NOT FIXED after its 5 internal iterations:
   - The failure may be CI-only. Compare its investigation log against the CI failure: is the failure mode the same, or did it manifest differently locally?
   - If the local failure mode genuinely matches the CI failure but no fix worked, treat this iteration of `pr-monitor` as exhausted — record it and either move on to a different failing job (if any) or count it toward `max_iterations` and move toward revert.
   - Do not push a speculative E2E fix without a local pass.

### 3.other — Unrecognised Job

Stop and ask the user. Do not guess fixes for unfamiliar workflows (publish, release, claude bot, etc.).

---

## Phase 4: Validate Locally, Then Push

Don't push until the relevant local checks are green. This is where most "blind push" cycles get caught.

1. **Run the canonical local validation gate** before every push:

   ```bash
   uv run invoke format lint
   ```

   This is the same set of checks that gates every PR (`Pre-Commit Hooks` job). If it fails, fix and re-run before pushing.

2. **Re-run the specific track's local check** that failed in Phase 3 (the targeted node, the frontend suite, etc.) to confirm the fix sticks.

3. **GraphQL regen guard.** If the diff includes any of `backend/styrmin_backend/api/schema/**` or any `.graphql` file, regenerate before committing:

   ```bash
   uv run styrmin export graphql-schema schema.graphql
   uv run invoke generate
   ```

   CI fails if `schema.graphql` or generated SDK types are stale.

4. **Stage and commit the fix.** One commit per iteration, with a clear message:

   ```bash
   git add <specific files>
   git commit -m "ci: fix <short description of what failed and what changed>"
   ```

   Append the commit SHA to `fix_commits`. Avoid `git add .` — be specific.

5. **Push to origin** (no force-push; these are new commits, not history rewrites):

   ```bash
   git push origin <branch>
   ```

6. **Increment `iteration`.** Record in `attempt_log[iteration]`:

   ```text
   {
       fix_summary:  <one line>,
       files_changed: <list>,
       commit_sha:   <new sha>,
       reproduced_locally: <true|false>,
       local_checks_passed: <true|false>,
   }
   ```

7. **If `iteration >= max_iterations`:** go to Phase 6 (revert). Otherwise return to Phase 1 to wait for the new CI run.

---

## Phase 5: Success — Report and Stop

1. Confirm one more time that all checks for the current SHA are green:

   ```bash
   gh pr checks <pr_number>
   ```

2. Produce the final report (see "Report Format" below) with `Result: GREEN after N iterations`.
3. Exit cleanly. Do **not** merge the PR — that is always the user's call.

---

## Phase 6: Revert — All Five Attempts Failed

If 5 iterations completed without reaching green, the fix attempts are likely misdirected. Roll the branch back to its pre-skill state so the user can take over with a clean slate.

1. **Confirm the revert plan with the user before executing.** Show:
   - The 5 fix commits that will be removed (`git log --oneline <baseline_commit>..HEAD`).
   - The baseline commit they will be reset to.
   - The fact that this is a force-push.
   - A summary of what each iteration tried (from `attempt_log`).

   Wait for explicit user approval. If the user wants to keep one or more of the fix commits, abort the revert and hand back to them with a written summary.

2. **After approval, reset the local branch:**

   ```bash
   git reset --hard <baseline_commit>
   ```

3. **Force-push with lease** so we don't clobber any commits the user may have pushed in parallel:

   ```bash
   git push --force-with-lease=<branch>:<fix_commits[-1]> origin <branch>
   ```

   The `--force-with-lease=<ref>:<expected_oid>` form ensures the push only succeeds if the remote tip is exactly the last commit this skill pushed. If the lease check fails, STOP — the user pushed something concurrently and the revert needs human review.

4. Produce the final report with `Result: NOT FIXED — reverted after 5 iterations`.

---

## Report Format

Always produce this report at the end, regardless of outcome.

```markdown
## PR Monitor Summary

**PR:** #<pr_number> — <title> (`<branch>`)
**Result:** GREEN after N iterations / NOT FIXED — reverted after 5 iterations
**Baseline commit:** `<short sha>`
**Final commit:** `<short sha>` (or "reverted to baseline")

### Iterations

#### Iteration 1
- **Failing job:** <name>
- **Failure summary:** <key log line(s)>
- **Reproduced locally:** yes / no (<reason if no>)
- **Fix applied:** <one-line description>
- **Files changed:** <list>
- **Local checks:** passed / skipped / failed
- **CI outcome after push:** green / still failing on <jobs>

#### Iteration 2
...

### CI-only failures (if any)
<List any failures that could not be reproduced locally and the evidence
gathered before pushing speculatively.>

### Current State
- Branch: `<branch>` at `<final sha>`
- Uncommitted changes: <yes/no — `git status --short`>
- Reverted: yes / no

### Recommendations
<If NOT FIXED: which iteration came closest, what hypotheses remain
untested, what a human should look at next.>
<If GREEN: any follow-up — flaky-looking failures, related tests to watch,
docs to update.>
```

---

## Important Guidelines

- **One fix per iteration.** Don't stack speculative changes. Apply one targeted change, push, and let CI tell you whether it worked.
- **Reproduce before you push.** A push without local reproduction is allowed only when the failure is genuinely CI-only — and you must say so explicitly in `attempt_log` and the final report.
- **Reproduce as narrowly as possible.** Run the **specific** failing tests/hooks, not the whole suite. Target the exact pytest node ID, the exact vitest test name, the exact pre-commit hook against the exact files. Widen one notch at a time only when a narrower invocation didn't match. Falling back to the full suite is a last resort and must be recorded in `attempt_log`. Never re-run the entire E2E directory.
- **No `--no-verify`.** Pre-commit hooks are the same checks CI runs. Bypassing them locally just delays the failure; fix the underlying issue.
- **No force-push outside revert.** Each fix is a new commit appended to the branch. The only force-push this skill performs is the Phase 6 revert, and only after explicit user approval.
- **Don't merge.** Even when CI goes green, this skill does not merge the PR. Report and stop.
- **Stay on the PR's branch.** Never switch branches mid-loop; never edit files while pytest/--pdb is paused on a different branch.
- **Defer to `/e2e-troubleshoot` for E2E.** That skill already implements the right reproduction loop with vcluster cleanup discipline. Don't duplicate it here.
- **Respect the constitution.** New behaviour shipped as part of a fix still needs E2E coverage and a propagation test where applicable (see `AGENTS.md` → "Always Do"). If a fix introduces new behaviour rather than just patching an existing path, flag this in the final report so the user knows additional coverage is owed.

## Expected Outcome

Either:

- **GREEN:** every required CI check on the PR's head SHA is `success` (or legitimately `skipped`), with a documented log of what was fixed and how each fix was validated locally.
- **NOT FIXED — reverted:** the branch is reset to its pre-skill baseline on both the local working tree and origin, with a documented log of the 5 attempts and why each one didn't work, ready for a human to pick up.
