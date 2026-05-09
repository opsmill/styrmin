---
name: bug-review
description: Review a bug-pipeline draft PR — verdict drives ready-for-review state. Posts a structured review comment and either marks the PR ready-for-review (satisfied) or keeps it in draft with requested changes (not satisfied).
argument-hint: PR number or full GitHub PR URL (e.g., `231` or `https://github.com/opsmill/styrmin/pull/231`)
compatibility: Requires GitHub access (`gh` CLI authenticated, or equivalent GitHub MCP/API tooling) with write access to pull requests on the target repository.
---

# Bug Pipeline — Review

## Introduction

`bug-review` is the fourth and **terminal** stage in the bug-fixing pipeline (`bug-analyze` → `bug-fix` → `bug-test` → `bug-review`). It is the AI quality gate that runs before a human reviewer ever sees the PR: it inspects the diff against project conventions and the analyst's hypothesis, then either flips the draft PR to ready-for-review (if satisfied) or keeps it in draft with a numbered list of requested changes (if not).

This skill is **distinct** from the existing general-purpose `@claude review` workflow defined in `.github/workflows/claude.yml`. That workflow performs a generic code review on any PR; `bug-review` is **pipeline-aware** — it cross-checks the diff against the analyst summary on the source bug issue, validates that test coverage exercises the recorded reproduction scenario, and owns the draft ↔ ready-for-review state transition for pipeline PRs. The two coexist; they do not replace each other.

The skill is runnable two ways with **identical** observable side effects:

- Locally from the Claude Code CLI: `/bug-review <pr>`.
- From the GitHub UI by typing `/bug-review <pr>` as a PR comment, which fires the matching `bug-agent-review.yml` workflow.

Because review is the terminal stage, this skill **never** suggests a next command — there is no `> Next:` line on either the satisfied or not-satisfied path.

## Prerequisites

- `gh` CLI authenticated against the target repository (or equivalent GitHub MCP/API tooling).
- Write access to pull requests on the target repository (needed to post the review comment and toggle ready-for-review).
- The target PR exists. **Typically** it is a draft PR opened by `bug-fix` and extended with regression tests by `bug-test`, but the skill MUST also handle:
  - PRs already in **ready-for-review** state (re-review on demand — see step 6).
  - PRs that a human reviewer manually flipped **back to draft** after a previous `bug-review` run marked them ready (see edge case in step 6).

## Arguments

<arguments> $ARGUMENTS </arguments>

The argument is a reference to a GitHub PR, accepted in either form:

- **Bare integer**: `231` — resolved against the current repository.
- **Full URL**: `https://github.com/opsmill/styrmin/pull/231` — the PR number is extracted from the path.

Both forms canonicalise to the same `(number, url)` pair internally and produce the same result.

## Main Tasks

### 1. Normalise the argument

Per the slash-command protocol, every stage that takes a PR argument MUST accept either form and normalise both to a canonical `(number, url)` pair.

1. If `$ARGUMENTS` is empty or contains only whitespace, **stop and post a usage comment** (see step 7). Do not guess a value, and do not perform any other side effect.
2. If the argument starts with `http`, parse it as a URL and extract the trailing integer from `/pull/<N>` (or `/pulls/<N>`).
3. Otherwise, treat the argument as a bare numeric identifier. Resolve the canonical URL by combining it with the repo URL from `gh repo view --json url --jq .url`.
4. If the result is not a positive integer, treat the input as malformed and post the usage comment per step 7. Do not proceed.

### 2. Fetch PR context

Pull the data the review needs in one shot:

```bash
gh pr view <PR-NNN> --json number,url,headRefName,baseRefName,isDraft,state,title,body,statusCheckRollup
gh pr diff <PR-NNN>
```

From this fetch, record:

- **`isDraft` and `state`** — needed for the verdict-driven state transition in step 6.
- **`headRefName` and `baseRefName`** — for sanity checks (the head ref is typically `bug/<NNN>-<short-description>`, but a non-pipeline PR is still in scope; do not gate on the pattern).
- **PR body** — extract the `Closes #<issue-NNN>` line. The integer following `#` is the source issue number; the analyst summary lives there. If the body has no `Closes #<issue-NNN>` line, record that fact and proceed — the review can still cover correctness/coverage/lint/conventions, but the cross-check against the analyst summary in step 3 will be skipped and noted in the review comment.
- **Full diff** — every file the PR touches, with line context. This is the primary subject of the review checks in step 4.
- **CI status if available** — `statusCheckRollup` lists check runs and their conclusions. Treat failed checks as a strong signal toward the not-satisfied verdict, but do not rely on CI alone; the review checks below are the agent's judgement.

### 3. Re-read the analyst summary on the source issue

Re-validating that the diff matches the originally hypothesised root cause is part of the review's job. The analyst summary lives on the **issue**, not on the PR — re-fetch it directly so the review doesn't depend on whatever the fix stage parsed earlier.

1. If the PR body has no `Closes #<issue-NNN>` line, skip this step and note in the review comment that no source issue was identified — the cross-check could not be performed.
2. Otherwise, fetch the issue's comments:

   ```bash
   gh issue view <issue-NNN> --json number,url,title,body,comments
   ```

3. Iterate the comments **from most recent to oldest** and pick the **first** comment whose body contains both markers `<!-- bug-pipeline:summary:start -->` and `<!-- bug-pipeline:summary:end -->` on their own lines. Do not fuzzy-match.
4. Parse the YAML between the markers and validate `schema_version: 1` plus the required fields (`issue.number`, `issue.url`, `hypothesis`, `affected_files`, `reproduction`, `short_description`) per `specs/010-bug-pipeline-skills/contracts/analyst-summary-schema.md`.
5. If parsing fails or no analyst comment is found, note that in the review comment and continue without the cross-check (the review's other checks still apply).
6. **Diff-vs-`affected_files` cross-check.** Compare the diff's file list against the analyst's `affected_files`. The `affected_files` list is a guide, not a hard contract — divergence is allowed. But if the diff materially diverges (e.g., touches files in a different subsystem, or skips most of the analyst's targets without explanation), call that out explicitly in the **correctness** paragraph of the review comment so a human reviewer knows the fix wandered from the recorded hypothesis.

### 4. Run the four review checks

These are the four substantive checks per FR-017. Each produces one paragraph in the review comment (step 5).

**(a) Correctness.** Does the diff plausibly fix the bug as described in the analyst summary's `hypothesis` and the originating issue body? Read the changed files and the call sites around them. Reason about whether the change addresses the root cause or only papers over the symptom. If the analyst summary was unavailable (step 3), reason about correctness against the issue body alone and say so explicitly.

**(b) Test coverage.** Are there tests on the same branch that exercise the analyst's `reproduction` scenario? Look for new or modified test files in the diff, and check that — at least conceptually — they would have failed before the fix and pass after it. If the `reproduction` list has multiple steps, every meaningful step should map to an assertion or setup line in the new tests. A diff with no new tests, or with tests that don't trace back to the reproduction scenario, is a strong signal toward the not-satisfied verdict.

**(c) Formatting and linting compliance.** Does the diff respect the project's coding standards? **The canonical command for this check lives in `AGENTS.md`** — do not hard-code a command here. The review describes what was *checked* (e.g., "the diff appears to follow the project's formatting and lint rules: import ordering is consistent, line lengths are within bounds, and no obvious type-hint omissions"); it does not need to *execute* the linter from inside the review skill. The maintainer can re-run the canonical command locally; if CI status (step 2) reports a failed lint job, that is also strong evidence and should be cited.

**(d) Convention adherence.** Does the change match the conventions documented in the root `AGENTS.md` and the per-component `AGENTS.md` files for the touched paths (e.g., `backend/AGENTS.md`, `frontend/AGENTS.md`, `python_sdk/AGENTS.md`)? Read those files for the components the diff touches and check the diff against their guidance. Examples of things to verify: GraphQL schema regeneration when the schema changed, propagation tests for new GraphQL fields, E2E coverage for new user-visible flows, `--pdb` discipline in new E2E tests, conventional-commit messages on the branch's commits. **Do not duplicate the AGENTS.md content here** — the review reads those files, applies them to this diff, and reports findings.

### 5. Compose the review comment

Post a **single** comment on the PR via `gh pr comment <PR-NNN> --body-file <path>` (or the equivalent `add_pull_request_comment` MCP call). The comment has a fixed structure:

```markdown
### Bug-pipeline review

**What I checked**

- **Correctness** — <one paragraph; cite specific files/functions; mention any divergence from the analyst's affected_files>.
- **Test coverage** — <one paragraph; map new tests back to the analyst's reproduction list; flag missing coverage>.
- **Lint/format** — <one paragraph; describe what was checked; cite CI lint job conclusion if present>.
- **Conventions** — <one paragraph; cite the per-component AGENTS.md files consulted; flag deviations>.

**Verdict**

<one of the verdict lines below>
```

The verdict line is **always exactly one of these two forms** — no ambiguity:

- **Satisfied**: a single line beginning with a green check, e.g. `✅ All checks passed — flipping this PR to ready-for-review.`
- **Not satisfied**: a warning line followed by a numbered list of requested changes, e.g.

  ```markdown
  ⚠️ Requested changes — keeping this PR in draft until addressed:

  1. <actionable item, naming a file or behaviour>
  2. <actionable item>
  3. <…>
  ```

The comment ends after the verdict block. **Do not** append a `> Next:` line on either path — review is the terminal stage, and the slash-command-protocol contract reserves next-stage suggestions for non-terminal stages only.

### 6. Verdict-driven state transition

This is the load-bearing part of the skill. The mapping from verdict to PR state is **explicit and one-to-one**:

| Verdict | Action on the PR |
|---------|------------------|
| **Satisfied** (✅) | Run `gh pr ready <PR-NNN>` to flip the draft PR to ready-for-review. |
| **Not satisfied** (⚠️) | Do **not** call `gh pr ready`. Leave the PR in draft. |

`gh pr ready` is called **only** on the satisfied path. On the not-satisfied path the skill posts the review comment and stops; the PR's draft state is preserved.

**Edge case — PR is already in ready-for-review when invoked.** A maintainer may re-run `/bug-review` on a PR that a previous run already flipped to ready-for-review (or on a PR that was never in draft to begin with). Still post the review comment — the maintainer asked for it. Then:

- If the new verdict is **satisfied**, no state change is needed (the PR is already in the satisfied state). Do not call `gh pr ready` redundantly. Note in the verdict line that the PR was already ready-for-review.
- If the new verdict is **not satisfied**, flip the PR back to draft with `gh pr ready --undo <PR-NNN>` and explain in the comment that the previous ready-for-review state has been reverted because new concerns were raised. The PR returns to draft until the requested changes are addressed and the next `/bug-review` run is satisfied.

**Edge case — PR was flipped back to draft by a human (per spec).** When `bug-review` is invoked again on a PR whose state is `draft` but where a previous review comment from this skill marked it satisfied, treat it as a fresh review against the **current state** — re-fetch the diff (the diff may have changed since the previous run), re-run the four checks, and produce a verdict from scratch. **Do not** assume the previous verdict still holds. Mention in the review comment that this is a re-review (e.g., a leading line like `_Re-review: this PR was previously flipped to ready-for-review and has since been reverted to draft. Re-evaluating against the current diff._`).

### 7. Handle missing or invalid arguments

Per `specs/010-bug-pipeline-skills/contracts/slash-command-protocol.md`, when triggered with no argument, an empty argument, or an argument that does not parse as a positive integer or canonical GitHub PR URL, the skill MUST:

1. Post a comment on the same PR (or issue, if the trigger surface was an issue comment) explaining the expected argument format and giving an example.
2. Stop without performing any other side effects (no review comment, no state change, no further comments).

Suggested usage-comment body:

```text
Usage: `/bug-review <pr>`

Argument is required and must be either a bare PR number or a full GitHub PR URL. Examples:

- `/bug-review 231`
- `/bug-review https://github.com/opsmill/styrmin/pull/231`
```

### 8. Failure path (any other unrecoverable failure)

If anything outside steps 2, 3 (handled non-fatally), 6, and 7 goes irrecoverably wrong (e.g., `gh pr view` cannot fetch the PR, `gh pr ready` fails after the satisfied verdict was posted, the diff cannot be retrieved), post a comment on the PR (or the issue, when no PR is in scope) that:

- Names what the stage was attempting at the point of failure.
- States plainly where the stage stopped.
- Describes any partial state — e.g., "the review comment was posted but `gh pr ready` failed; the PR is still in draft despite the satisfied verdict" — so the maintainer can finish the transition manually.
- Does **not** include a `> Next:` suggestion line. Review is the terminal stage; failure paths never suggest a next stage either.

## Examples

**Satisfied review comment** (≤20 lines):

```markdown
### Bug-pipeline review

**What I checked**

- **Correctness** — `build_pod_template` now guards `spec.containers` and raises `EmptySpecError`. Diff matches the analyst's `affected_files` (`backend/styrmin_backend/services/cluster.py`).
- **Test coverage** — `backend/tests/services/test_cluster.py::test_build_pod_template_rejects_empty_containers` exercises the analyst's reproduction scenario and asserts the new error path.
- **Lint/format** — Diff respects ruff/`ty` conventions; CI lint job is green.
- **Conventions** — Matches `backend/AGENTS.md`: regression test in the right tier, conventional-commit messages on both commits.

**Verdict**

✅ All checks passed — flipping this PR to ready-for-review.
```

**Not-satisfied review comment** (≤20 lines):

```markdown
### Bug-pipeline review

**What I checked**

- **Correctness** — Fix in `backend/styrmin_backend/services/cluster.py` looks plausible, but it touches `frontend/src/cluster/ClusterCard.tsx` too — that file is not in the analyst's `affected_files` and the change there is unrelated to the reproduction.
- **Test coverage** — No new tests in the diff. The analyst's `reproduction` list has three steps and none are covered.
- **Lint/format** — CI lint job is failing (`E501 line too long` in `services/cluster.py`).
- **Conventions** — `backend/AGENTS.md` requires E2E coverage for new user-visible flows; none added.

**Verdict**

⚠️ Requested changes — keeping this PR in draft until addressed:

1. Drop the unrelated `ClusterCard.tsx` change or move it to a separate PR.
2. Add a regression test covering the empty-`spec.containers` reproduction.
3. Run `uv run invoke format lint` and resolve the `E501` violation.
4. Add an E2E scenario per `backend/AGENTS.md` "Always Do".
```

## Notes

- This skill **only** posts a review comment and may toggle the draft / ready-for-review state. It never writes code, never amends commits, never edits prior comments, and never invokes downstream stages (there are none — review is terminal).
- **Verdict-to-state mapping is one-to-one and explicit**: satisfied → `gh pr ready <PR>`; not satisfied → no `gh pr ready` call. The only exception is the already-ready re-review case, where a not-satisfied verdict triggers `gh pr ready --undo <PR>` to flip the PR back to draft.
- This skill is **distinct** from the general-purpose `@claude review` workflow in `.github/workflows/claude.yml`. That workflow performs generic review on any PR; `bug-review` is pipeline-aware (cross-checks the analyst summary, owns the draft ↔ ready-for-review transition, and only suggests changes scoped to the bug being fixed). Both coexist.
- Coding-convention questions (lint command, where tests live, layered architecture rules, GraphQL regeneration, E2E discipline) defer to `AGENTS.md` and per-component `AGENTS.md` files. Do not duplicate that content here.
- The pipeline works on **any** issue/PR regardless of labels (FR-022). Do not gate on labels.
- Review is the **terminal** stage. The output comment never ends with a `> Next:` suggestion on either path.

## Expected Outcome

On the **satisfied** verdict: a single review comment posted on the PR with a "What I checked" section and a `✅`-prefixed verdict line, and the PR transitioned from draft to ready-for-review via `gh pr ready`. No `> Next:` suggestion. No other side effects.

On the **not-satisfied** verdict: a single review comment posted on the PR with a "What I checked" section, a `⚠️`-prefixed verdict line, and a numbered list of requested changes. The PR remains in draft (or, in the already-ready re-review case, is flipped back to draft via `gh pr ready --undo`). No `> Next:` suggestion. No other side effects.

On any failure path (missing/invalid argument, unrecoverable error fetching PR or issue context, `gh pr ready` failure after a satisfied verdict): a comment posted on the PR (or the issue, when no PR is in scope) describing what was attempted and where the stage stopped, **no `> Next:` suggestion**, and no further state changes beyond what completed before the failure.

In neither case does the skill edit or delete prior comments, and in no case does it auto-fire a next stage — there is none.
