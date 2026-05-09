---
name: bug-test
description: Extend a bug-fix-produced draft PR with regression tests on the same branch — write or extend tests covering the analyst's reproduction scenario, run the project's standard test command, and post a PR comment naming what was tested.
argument-hint: Issue number, PR number, or full GitHub URL of either (e.g., `206`, `231`, `https://github.com/opsmill/styrmin/issues/206`, or `https://github.com/opsmill/styrmin/pull/231`)
compatibility: Requires GitHub access (`gh` CLI authenticated, or equivalent GitHub MCP/API tooling) with write access to pull requests and contents on the target repository.
---

# Bug Pipeline — Test

## Introduction

`bug-test` is the third of four stages in the bug-fixing pipeline (`bug-analyze` → `bug-fix` → `bug-test` → `bug-review`). It **extends** the draft pull request opened by `bug-fix` with regression tests that exercise the analyst's reproduction scenario, on the **same branch** as the fix so the fix and its tests travel together to review.

The skill is runnable two ways with **identical** observable side effects:

- Locally from the Claude Code CLI: `/bug-test <issue|pr>`.
- From the GitHub UI by typing `/bug-test <issue|pr>` as an issue or PR comment, which fires the matching `bug-agent-test.yml` workflow.

Stages chain via a hybrid model — every stage is human-triggered, and on success the closing line of this skill's output comment names the next command. This skill never auto-fires the next stage.

## Prerequisites

- `gh` CLI authenticated against the target repository (or equivalent GitHub MCP/API tooling).
- Write access to pull requests and contents on the target repository.
- An **open draft PR** linked to the bug issue (via `Closes #<NNN>` in its body) already exists, opened by a prior `/bug-fix` run.
- The PR's head branch matches the pattern `bug/<NNN>-<short_description>` per the fix-stage contract.
- A working tree of the repository so the agent can check out the fix branch and run the test command.

## Arguments

<arguments> $ARGUMENTS </arguments>

The argument is a reference to either the bug **issue** or the **PR** opened against it, accepted in either form:

- **Bare integer**: `206` (issue) or `231` (PR) — resolved against the current repository.
- **Full URL**: `https://github.com/opsmill/styrmin/issues/206` or `https://github.com/opsmill/styrmin/pull/231` — the number is extracted from the path.

Both forms canonicalise to a `(number, url, kind)` triple internally, where `kind` is `issue` or `pr`.

## Main Tasks

### 1. Normalise the argument

Per the slash-command protocol, every stage that takes an issue/PR argument MUST accept either form and normalise both to a canonical pair.

1. If `$ARGUMENTS` is empty or contains only whitespace, **stop and post a usage comment** (see step 8). Do not guess a value, and do not perform any other side effect.
2. If the argument starts with `http`, parse it as a URL: extract the trailing integer from `/issues/<N>` (set `kind=issue`) or `/pull/<N>` (set `kind=pr`).
3. Otherwise, treat the argument as a bare numeric identifier. Resolve the canonical repo URL via `gh repo view --json url --jq .url`; the kind is determined in step 2 below by querying GitHub.
4. If the result is not a positive integer, treat the input as malformed and post the usage comment per step 8. Do not proceed.

### 2. Locate the open draft PR linked to the bug issue

The test stage's contract with `bug-fix` is the open draft PR whose body contains `Closes #<NNN>`.

1. **If the argument was an issue (`kind=issue`)**: search for the draft PR that closes it.

   ```bash
   gh pr list --state open --draft --search "is:pr in:body Closes #<NNN>" \
     --json number,url,headRefName,isDraft,body
   ```

   Filter the results to the PR whose body actually contains `Closes #<NNN>` on its own (avoid spurious matches like `Closes #1234` when looking for `#123`). If multiple match, prefer the most recently updated.

2. **If the argument was a PR (`kind=pr`)**: fetch it directly.

   ```bash
   gh pr view <PR-NNN> --json number,url,headRefName,isDraft,body,state
   ```

   Parse the body for a `Closes #<issue-NNN>` line and record the issue number — the analyst summary lives on the issue, not on the PR.

3. **Failure path** if any of the following hold:
   - No open draft PR is found for the issue.
   - The PR is not in `draft` state, or is closed/merged.
   - The PR body has no `Closes #<NNN>` line that resolves to a real issue number.

   In the failure case: post a comment on the issue (or the PR if `kind=pr`) naming what was looked for ("an open draft PR with `Closes #<NNN>` in its body") and instructing the maintainer to run `/bug-fix <NNN>` first or to reopen the draft. **Stop.** Do not check anything out, do not write tests, do not commit.

### 3. Verify the fix branch matches `bug/<NNN>-*`

The branch name is the load-bearing handle that ties the fix, its tests, and downstream `/bug-review` together.

1. Read the PR's `headRefName` from step 2.
2. Confirm it matches the regex `^bug/[0-9]+-` (numeric issue prefix, kebab-case continuation).
3. **Failure path** if it does not match: post a comment on the PR naming the actual head ref and the expected pattern (`bug/<NNN>-<short-description>`), and **stop**. Do not check it out, do not write tests, do not push. Branch-mismatch means the PR was likely opened outside the pipeline, and the test stage cannot safely extend it.

### 4. Re-fetch the analyst summary from the linked issue

The analyst's `reproduction` field guides what behaviour the new tests must cover. The summary lives on the **issue**, not on the PR — re-fetch it directly so the test stage doesn't depend on the fix stage's parsing.

1. Fetch the issue's comments:

   ```bash
   gh issue view <issue-NNN> --json number,url,title,body,comments
   ```

2. Iterate the comments **from most recent to oldest** and pick the **first** comment whose body contains both markers `<!-- bug-pipeline:summary:start -->` and `<!-- bug-pipeline:summary:end -->` on their own lines. Do not fuzzy-match — the markers are stable anchors.
3. Extract the YAML between the markers (strip the surrounding ```` ```yaml ```` / ```` ``` ```` fence) and parse it.
4. **Validate** the parsed object against the schema in `specs/010-bug-pipeline-skills/contracts/analyst-summary-schema.md`:
   - `schema_version` MUST equal `1`. Any other value (or a missing field) is a parse failure.
   - Required fields: `issue.number`, `issue.url`, `hypothesis`, `affected_files`, `reproduction`, `short_description`.
5. **Failure path** if no valid summary is found, the schema mismatches, or `reproduction` is empty: post a comment on the PR explaining what was looked for, and **stop**. Do not write tests against guessed behaviour.

The `reproduction` list is the primary input for step 6 — every step in that list should map (where meaningful) to an assertion in the new or extended tests.

### 5. Check out the fix branch

Work directly on the fix branch — **never create a new branch.** Per FR-014 the test stage MUST add or modify tests on the same branch as the fix, not on a new branch. Do not create `bug/<NNN>-tests`, do not create `bug/<NNN>-<short>-tests`, do not branch off the fix branch. The test commits land on top of the fix commits on the same ref.

1. If the working tree is dirty, stash or commit the noise away first; the test stage requires a clean checkout.
2. Fetch and check out the fix branch:

   ```bash
   git fetch origin bug/<NNN>-<short_description>
   git checkout bug/<NNN>-<short_description>
   git pull --ff-only origin bug/<NNN>-<short_description>
   ```

3. If `git pull --ff-only` fails (the local branch has diverged), reset to `origin/bug/<NNN>-<short_description>` only after confirming there is no local work to lose; otherwise, treat the divergence as a failure path per step 8 and stop.

### 6. Write or extend tests covering the reproduction scenario

The job here is to choose the right test file and write tests that exercise the previously-broken behaviour from the analyst's `reproduction` list, so that **without** the fix the test would fail and **with** the fix it passes.

1. **Choose the location.** Look at the analyst's `affected_files` and the actual diff already on the branch (`git diff origin/develop... -- '**/*.py' '**/*.ts' '**/*.tsx'` etc.). Identify the closest existing test file for the changed code:
   - If a related test file exists for the affected module, **extend** it with a new test case rather than creating a parallel file.
   - If no related test exists, create a new test file at the location the existing project conventions place tests for that subsystem.
2. **Defer to `AGENTS.md` for test command, test directory layout, test tier (unit/integration/E2E), and test conventions.** The root `AGENTS.md` and per-component `AGENTS.md` files (backend, frontend, python_sdk) are the source of truth — read them. The test stage's job is to pick the right tier for the bug being fixed and the right file within that tier; it is **not** the test stage's job to redefine where tests go.
3. **Write the tests.** Each test should:
   - Carry a comment naming the issue (e.g., `# Regression for #<NNN>` or `// Regression for #<NNN>`) so future readers can trace it back to the analyst summary.
   - Map (where meaningful) to a step in the analyst's `reproduction` list — set up the input from the reproduction, exercise the path, assert the expected post-fix behaviour.
   - Keep the scope tight: cover the reproduced bug, not adjacent functionality.
4. Stage and commit the test changes with a conventional-commit message (e.g., `test: add regression for #<NNN> …`). Do **not** push yet — the test command must succeed first (step 7).

### 7. Run the project's standard test command

1. Run the project's standard test command **as documented in `AGENTS.md`** for the tier you wrote tests in. Do not hard-code a command here — the source of truth lives in `AGENTS.md`.
2. **If the test command exits non-zero, this is the failure path.**
   - Post a comment on the PR containing the failing test output **verbatim** in a fenced code block (use a triple backtick fence; preserve line breaks). Prepend a one-paragraph prose explanation that tests were written but did not pass.
   - **Do NOT push the test commit.** The local commit is left in place so the maintainer can check out the branch, inspect what was attempted, and either fix the test or re-run `/bug-test`.
   - **Do NOT include a `> Next:` suggestion line.** Failure paths never suggest a next stage.
   - **Stop.**
3. If the test command exits zero, continue to step 8.

### 8. Push the test commits and post the success comment

1. Push the test commits to the **same** branch on `origin`:

   ```bash
   git push origin bug/<NNN>-<short_description>
   ```

   Do not use `--force`; the push should fast-forward over the existing fix commits. If it cannot, the branch was rewritten between step 5 and now — treat that as a failure path (step 9).

2. Post a single comment on the **PR** (not on the issue) that:
   - Names what was tested in 1–3 lines (which behaviour is now covered, what kind of tests were added).
   - Lists the test file(s) added or extended (repo-relative paths).
   - Ends with a final line: `> Next: \`/bug-review <PR-number>\``.

   Do not edit prior comments. The pipeline only ever appends.

### 9. Handle missing or invalid arguments

Per `specs/010-bug-pipeline-skills/contracts/slash-command-protocol.md`, when triggered with no argument, an empty argument, or an argument that does not parse as a positive integer or canonical GitHub URL, the skill MUST:

1. Post a comment on the same issue/PR explaining the expected argument format and giving an example.
2. Stop without performing any other side effects (no checkout, no commits, no further comments).

Suggested usage-comment body:

```text
Usage: `/bug-test <issue|pr>`

Argument is required and must be either a bare issue or PR number, or a full
GitHub issue or PR URL. Examples:

- `/bug-test 206`
- `/bug-test 231`
- `/bug-test https://github.com/opsmill/styrmin/issues/206`
- `/bug-test https://github.com/opsmill/styrmin/pull/231`
```

### 10. Failure path (any other unrecoverable failure)

If anything outside steps 2, 3, 4, 7, and 9 goes irrecoverably wrong (e.g., `git push` fails after the test commit, the PR head ref is updated mid-run, the test file location cannot be determined), post a comment on the PR (or the issue if no PR is yet known) that:

- Names what the stage was attempting at the point of failure.
- States plainly where the stage stopped.
- Describes any partial state — e.g., "a test commit was made locally but the branch was not pushed" — so the maintainer can clean up.
- Does **not** include a `> Next:` suggestion line.

If the partial state includes local commits that were not pushed, leave them in place; the maintainer can check out the branch and decide whether to keep, amend, or drop them.

## Examples

**Success comment on the PR** (≤20 lines):

```markdown
### Regression tests added

Added a unit test that exercises `build_pod_template` with an empty
`spec.containers` list and asserts the new `EmptySpecError` is raised
instead of the previous unguarded `IndexError`. The project test command
passes against the branch.

Files:

- `backend/tests/services/test_cluster.py` — new test `test_build_pod_template_rejects_empty_containers` (regression for #206).

> Next: `/bug-review 231`
```

**Test-failure comment on the PR** (≤20 lines):

````markdown
### Test stage stopped — regression tests did not pass

I added regression tests for #206 covering the analyst's reproduction
steps, but the project test command failed. The test commit was **not
pushed**. Output below; please address the failures (or fix the test) and
re-run `/bug-test 206`.

```text
backend/tests/services/test_cluster.py::test_build_pod_template_rejects_empty_containers FAILED
AssertionError: expected EmptySpecError, got IndexError: list index out of range
```
````

## Notes

- This skill **only** extends the existing fix branch. It MUST NOT create a new branch — per FR-014, tests travel on the same branch as the fix. Do not create `bug/<NNN>-tests`, do not branch off the fix branch, do not push to a different ref.
- This skill **only** consumes the analyst's machine-readable summary block and the existing fix branch. It does not re-investigate the issue, does not modify the fix, and does not re-run lint/format on the fix's diff.
- The test command is **delegated to `AGENTS.md`**. Do not hard-code a tool name here. The right command depends on which tier of the test pyramid the new tests live in; `AGENTS.md` and the per-component `AGENTS.md` files document which tier is appropriate for which kind of change.
- The pipeline works on **any** issue regardless of labels (FR-022). Do not gate on labels.
- Coding-convention questions (where tests live, what command runs the test suite, layered architecture rules, GraphQL regeneration) defer to `AGENTS.md`. Do not duplicate that content here.

## Expected Outcome

On success: one or more new commits on the existing `bug/<NNN>-<short_description>` branch (same branch as the fix; not a new branch), tests that exercise the analyst's reproduction scenario and pass when the project's standard test command is run, and a PR comment naming what was tested and ending with `> Next: /bug-review <PR-number>`.

On any failure path (no draft PR, branch-pattern mismatch, missing or malformed analyst summary, tests fail, or any other irrecoverable error): a comment posted on the PR (or the issue, when no PR is in scope) describing what was attempted and where the stage stopped, **no remote test commits**, and **no `> Next:` suggestion**.

In neither case does the skill edit or delete prior comments, and in no case does it auto-fire the next stage.
