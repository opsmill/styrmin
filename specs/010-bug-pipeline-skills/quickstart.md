# Quickstart: Bug-Fixing Pipeline Smoke Test

This walkthrough exercises the four pipeline stages end-to-end on a sandbox issue. It doubles as the v1 manual smoke-test procedure (the test substitute documented in `plan.md`'s Complexity Tracking).

## Prerequisites

- A bug issue you control in `opsmill/styrmin` (or a sandbox fork). For each test, prefer a small reproducible bug with a clear repro: e.g., a typo in an error message that has a unit test attached, or a missing default in a config object.
- Local: Claude Code CLI authenticated; `gh` CLI authenticated as a user with write access to issues and PRs.
- CI: `ANTHROPIC_API_KEY` secret already configured (used by `claude.yml`); the four new workflow files merged to `develop`.

## Stage-by-stage walkthrough

### 1. Analyze (issue → analyst comment)

**Trigger from CLI**:

```bash
claude
> /bug-analyze 206
```

**Trigger from GitHub**: paste a comment on the issue with body `/bug-analyze 206`.

**Expected observable outcomes**:
1. A new comment is posted on the issue.
2. The comment contains, in order: a hypothesis paragraph, a list of affected files, numbered reproduction steps, a fenced YAML block bracketed by `<!-- bug-pipeline:summary:start -->` / `:end -->`, and a final `> Next: /bug-fix 206` line.
3. The YAML parses (`yq` or any YAML reader) and matches `contracts/analyst-summary-schema.md`.

**Failure-path check**: trigger the same command on an issue with a one-line vague description (e.g., "doesn't work"). The analyst SHOULD post a failure comment that names what it inspected and why it could not form a hypothesis, and SHOULD NOT include a `next_command` suggestion.

### 2. Fix (analyst comment → branch + draft PR)

**Trigger**: `/bug-fix 206` (CLI or GitHub comment on the issue).

**Expected observable outcomes**:
1. A branch named `bug/206-<short_description>` exists on the remote.
2. A draft PR is open against `develop`, body contains `Closes #206`.
3. The PR body has a `<details>` section labelled "Analyst summary (machine-readable)" containing the verbatim YAML block from the analyst comment.
4. `git diff develop..bug/206-<short_description>` shows changes that match the analyst's hypothesis.
5. `uv run invoke format lint` passes against the diff (verify locally if you're testing from CLI).
6. The fix stage's output comment (on the issue) ends with `> Next: /bug-test 206`.

**Failure-path check**: trigger `/bug-fix 206` on an issue that has no analyst comment yet. Expect: a failure comment on the issue saying analysis is required first; **no** branch pushed, **no** PR opened.

### 3. Test (draft PR → tests on same branch)

**Trigger**: `/bug-test 206` (issue or PR comment) or `/bug-test <pr-number>`.

**Expected observable outcomes**:
1. New commit(s) on the same `bug/206-*` branch, modifying or adding files under the project's test directories.
2. The test stage's output comment on the PR summarises what was tested.
3. Running the project's standard test command on the branch passes.
4. The output comment ends with `> Next: /bug-review <pr-number>`.

### 4. Review (PR → review comment + state)

**Trigger**: `/bug-review <pr-number>` (PR comment).

**Expected observable outcomes — pass case**:
1. A review comment is posted on the PR listing what was checked.
2. The PR transitions to ready-for-review.
3. No `Next:` suggestion (review is the terminal stage).

**Expected observable outcomes — fail case**: the review identifies a real or seeded issue (e.g., introduce a lint violation in the fix branch first).
1. Review comment lists the requested changes.
2. PR remains in **draft**.
3. No `Next:` suggestion.

## Smoke-test acceptance

The pipeline passes the v1 smoke test when all four stages produce the expected outcomes above on at least one well-described bug issue, and **at least one failure-path** has been verified for each of `bug-analyze` and `bug-fix`. Record the validating run's URLs in the PR description for this feature.

## Local-vs-CI parity check

After the CI run, repeat the analyze stage **locally** for the same issue (in a clean checkout). Verify that the locally-produced comment text and YAML block are functionally equivalent to the CI-produced one (semantic match, not byte-for-byte — the LLM is non-deterministic). Any logic-level divergence (e.g., a field present locally but missing in CI) is a bug.

## Troubleshooting

- **Workflow doesn't fire**: confirm the comment body starts with the slash command and a single space (e.g., `/bug-analyze 206`, not `/bug-analyze:206` or quoted in a blockquote).
- **Action error "no analyst comment found"** in the fix stage: check that the most recent analyst comment on the issue contains the `<!-- bug-pipeline:summary:start -->` / `:end -->` markers and a parseable YAML block.
- **Branch already exists** in the fix stage: delete or rename `bug/<NNN>-*` and re-run.
- **Lint failure in fix stage**: read the failure comment; the lint output is included verbatim. Fix manually on the branch and re-trigger `/bug-test`.
