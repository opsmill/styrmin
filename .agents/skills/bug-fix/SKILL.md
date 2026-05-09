---
name: bug-fix
description: Consume the most recent analyst summary on a bug issue and produce a draft pull request — branch, fix commit, lint-clean diff, and analyst context embedded in the PR body — ready for the test stage.
argument-hint: Issue number or full GitHub issue URL (e.g., `206` or `https://github.com/opsmill/styrmin/issues/206`)
compatibility: Requires GitHub access (`gh` CLI authenticated, or equivalent GitHub MCP/API tooling) with write access to issues, pull requests, and contents on the target repository. Assumes the project's default branch is `develop`.
---

# Bug Pipeline — Fix

## Introduction

`bug-fix` is the second of four stages in the bug-fixing pipeline (`bug-analyze` → `bug-fix` → `bug-test` → `bug-review`). It **consumes** the structured analyst summary produced by `bug-analyze` and **produces** a draft pull request: a fix branch named `bug/<NNN>-<short_description>`, the actual code change, lint/format-clean against `uv run invoke format lint`, and a PR description that embeds the analyst's machine-readable summary so reviewers have full context without leaving the PR view.

The skill is runnable two ways with **identical** observable side effects:

- Locally from the Claude Code CLI: `/bug-fix <issue>`.
- From the GitHub UI by typing `/bug-fix <issue>` as an issue comment, which fires the matching `bug-agent-fix.yml` workflow.

Stages chain via a hybrid model — every stage is human-triggered, and on success the closing line of this skill's output comment names the next command. This skill never auto-fires the next stage.

## Prerequisites

- `gh` CLI authenticated against the target repository (or equivalent GitHub MCP/API tooling).
- Write access to issues, pull requests, and contents on the target repository.
- A clean git working tree on the project's default branch (`develop`). The skill creates a new branch from `develop` and refuses to proceed if the target branch already exists locally or on `origin`.
- A prior `bug-analyze` run has posted at least one valid analyst comment with a `schema_version: 1` summary block on the target issue.

## Arguments

<arguments> $ARGUMENTS </arguments>

The argument is a reference to a GitHub issue, accepted in either form:

- **Bare integer**: `206` — resolved against the current repository.
- **Full URL**: `https://github.com/opsmill/styrmin/issues/206` — the issue number is extracted from the path.

Both forms canonicalise to the same `(number, url)` pair internally and produce the same result.

## Main Tasks

### 1. Normalise the argument

Per the slash-command protocol, every stage that takes an issue argument MUST accept either form and normalise both to a canonical `(number, url)` pair.

1. If `$ARGUMENTS` is empty or contains only whitespace, **stop and post a usage comment** (see step 9). Do not guess a value, and do not perform any other side effect.
2. If the argument starts with `http`, parse it as a URL and extract the trailing integer from `/issues/<N>` (or `/pull/<N>`).
3. Otherwise, treat the argument as a bare numeric identifier. Resolve the canonical URL by combining it with the repo URL from `gh repo view --json url --jq .url`.
4. If the result is not a positive integer, treat the input as malformed and post the usage comment per step 9. Do not proceed.

### 2. Locate the analyst summary

The fix stage's contract with `bug-analyze` is the fenced YAML block bracketed by `<!-- bug-pipeline:summary:start -->` / `<!-- bug-pipeline:summary:end -->` markers. The schema is documented verbatim in `specs/010-bug-pipeline-skills/contracts/analyst-summary-schema.md`.

1. Fetch the issue's comments:

   ```bash
   gh issue view <NNN> --json number,url,title,body,comments
   ```

2. Iterate the comments **from most recent to oldest** and pick the **first** comment whose body contains both markers. Do not fuzzy-match — the markers are stable anchors and must appear exactly as `<!-- bug-pipeline:summary:start -->` and `<!-- bug-pipeline:summary:end -->` on their own lines.
3. Extract the YAML between the markers (strip the surrounding ```` ```yaml ```` / ```` ``` ```` fence) and parse it.
4. **Validate** the parsed object against the schema:
   - `schema_version` MUST equal `1`. Any other value (or a missing field) is a parse failure.
   - Required fields: `issue.number`, `issue.url`, `hypothesis`, `affected_files`, `reproduction`, `short_description`. `short_description` MUST match `^[a-z0-9][a-z0-9-]{0,39}$`.
5. **Failure path** if any of the following hold:
   - No comment on the issue contains both markers.
   - The most recent matching comment fails YAML parsing.
   - `schema_version` is missing or not `1`.
   - A required field is missing or violates its type/regex constraint.

   In the failure case: post a comment on the issue stating exactly what was looked for (the markers, schema_version 1, the missing/invalid field), and **stop**. Do **not** create a branch, do **not** push, do **not** open a PR. The closing prose should point the maintainer at re-running `/bug-analyze` if no analyst comment exists yet.

The most-recent rule lets a maintainer re-run `/bug-analyze` to supersede a stale or wrong earlier analysis without deleting comments — every stage appends, never edits.

### 3. Create the fix branch

The fix branch is named `bug/<NNN>-<short_description>` rooted at the project's default branch (`develop`). Per research §R5 the policy is **fail loudly on collision** — never auto-suffix, never reuse-and-amend.

1. Resolve `<short_description>` as the analyst's `short_description` field, verbatim. It already conforms to `^[a-z0-9][a-z0-9-]{0,39}$` (validated in step 2).
2. Compose the branch name: `bug/<NNN>-<short_description>`.
3. Check for collisions on **both** sides:
   - Local: `git rev-parse --verify --quiet refs/heads/bug/<NNN>-<short_description>`.
   - Remote: `git ls-remote --heads origin bug/<NNN>-<short_description>` and confirm the output is empty.
4. **Failure path** if either check finds an existing branch: post a comment on the issue naming the colliding branch and the side it lives on (local, remote, or both), and instructing the maintainer to delete or rename the existing branch and re-run `/bug-fix`. Do **not** create a new branch, do **not** push, do **not** open a PR. Do **not** auto-suffix the name.
5. Otherwise, create the branch from a fresh `develop`:

   ```bash
   git fetch origin develop
   git checkout -b bug/<NNN>-<short_description> origin/develop
   ```

### 4. Implement the fix

Apply the actual code change guided by the analyst's `hypothesis`, `affected_files`, and `reproduction`.

1. Read each of the analyst's `affected_files` and the surrounding code. The analyst may have widened or under-localised the search; treat the list as a starting point, not a hard constraint. If `affected_files` is `[]` (empty), broaden the search using the issue body and `hypothesis` as guidance.
2. Make the change. Keep the diff scoped to the bug — do not refactor adjacent code, do not touch unrelated files.
3. **Defer all coding-convention questions to the existing `AGENTS.md` files** (root + per-component). Do not paraphrase or duplicate that content here. If you need to know where tests live, what command runs the test suite, or how the layered architecture is organised, read `AGENTS.md` and the relevant `dev/guidelines/` entries.
4. Stage and commit the change with a conventional-commit message (e.g., `fix: …`). Do **not** push yet — formatting/linting must succeed first (step 5).

### 5. Run format and lint

Project formatting and linting are a hard gate before push and PR per FR-010 / FR-012.

1. Run the project's standard format + lint command:

   ```bash
   uv run invoke format lint
   ```

2. **If the command exits non-zero, this is the failure path.** It does not matter whether the failure is a format diff, a ruff violation, a `ty` type error, or any other check inside the invoke target — any non-zero exit means the fix stage stops here.

   On lint/format failure:
   - Post a comment on the issue containing the lint output **verbatim** in a fenced code block (use a triple backtick fence; preserve line breaks). Prepend a one-paragraph prose explanation that the fix was implemented but the format/lint gate failed.
   - **Do NOT push the branch.**
   - **Do NOT open a PR.**
   - **Stop.** The local commit on the branch is left in place so the maintainer can `git switch bug/<NNN>-<short_description>` and address the violations manually if they want; the absence of a remote branch makes this unambiguously a failure.

3. If `uv run invoke format lint` made formatting changes, amend or add a follow-up commit so the branch is lint-clean before continuing. Re-run the command until it exits zero.

### 6. Push the branch

After format and lint pass, push the branch upstream:

```bash
git push -u origin bug/<NNN>-<short_description>
```

### 7. Open the draft pull request

Open a **draft** PR against `develop` using the template from research §R6. The PR title is a concise, human-readable summary of the bug being fixed (under ~70 chars).

**PR body template** (substitute the analyst's verbatim YAML and reproduction list):

````markdown
Closes #<NNN>

## Summary

<2–3 line description of the fix, derived from the analyst's hypothesis and the actual change>

<details>
<summary>Analyst summary (machine-readable)</summary>

```yaml
schema_version: 1
issue:
  number: <NNN>
  url: <canonical issue URL>
hypothesis: |
  <verbatim from analyst>
affected_files:
  - <verbatim>
reproduction:
  - "<verbatim>"
short_description: <verbatim>
next_command: /bug-fix <NNN>
```

</details>

## Test plan

- [ ] <reproduction step 1, verbatim from the analyst>
- [ ] <reproduction step 2, verbatim from the analyst>
- [ ] <…>
````

Notes on the body:

- `Closes #<NNN>` is the **first** line of the body — it triggers GitHub's auto-close-on-merge behaviour and is required by FR-011a.
- The `<details>` block contains the analyst YAML **verbatim** (do not edit, summarise, or reformat it). FR-011b requires reviewers to have full context inside the PR view.
- The test-plan checkboxes are **unchecked** — the test stage will tick them as it adds tests covering each reproduction step.

Open the PR:

```bash
gh pr create --draft \
  --base develop \
  --head bug/<NNN>-<short_description> \
  --title "<concise title>" \
  --body-file <path-to-body>
```

(Or the equivalent `create_pull_request` MCP call.)

### 8. Post the success comment on the issue

Post a single comment on the **issue** (not on the PR) that:

- Names what was changed (1–3 lines, business-value framing).
- Includes the PR URL.
- Ends with a final line: `> Next: \`/bug-test <NNN>\``.

Do not edit prior comments. The pipeline only ever appends.

### 9. Handle missing or invalid arguments

Per `specs/010-bug-pipeline-skills/contracts/slash-command-protocol.md`, when triggered with no argument, an empty argument, or an argument that does not parse as a positive integer or canonical GitHub URL, the skill MUST:

1. Post a comment on the same issue/PR explaining the expected argument format and giving an example.
2. Stop without performing any other side effects (no branch, no PR, no further comments).

Suggested usage-comment body:

```text
Usage: `/bug-fix <issue>`

Argument is required and must be either a bare issue number or a full GitHub issue URL. Examples:

- `/bug-fix 206`
- `/bug-fix https://github.com/opsmill/styrmin/issues/206`
```

### 10. Failure path (any other unrecoverable failure)

If anything outside steps 2, 3, 5, and 9 goes irrecoverably wrong (e.g., `gh pr create` fails after the branch is pushed, the working tree is dirty before step 3, the analyst's `affected_files` are unreadable), post a comment on the issue that:

- Names what the stage was attempting at the point of failure.
- States plainly where the stage stopped.
- Describes any partial state — e.g., "a commit was made locally but the branch was not pushed", or "the branch was pushed but the PR was not opened" — so the maintainer can clean up.
- Does **not** include a `> Next:` suggestion line. Failure paths never suggest a next stage.

If the partial state includes a pushed branch with no PR, leave the branch in place; the maintainer can either delete it or open the PR manually. Do **not** silently delete it.

## Examples

**Success comment on the issue** (≤20 lines):

```markdown
### Fix proposed — draft PR opened

Guarded `build_pod_template` against an empty `spec.containers` list and added
input validation in the GraphQL schema layer. Format and lint pass cleanly.

PR: https://github.com/opsmill/styrmin/pull/231 (draft)

> Next: `/bug-test 206`
```

**Lint-failure comment on the issue** (≤20 lines):

````markdown
### Fix stage stopped — `uv run invoke format lint` failed

The fix was implemented on a local commit, but `uv run invoke format lint`
reported violations and the branch was **not pushed** and the PR was **not
opened**. Output below; please address the violations and re-run `/bug-fix 206`.

```text
backend/styrmin_backend/services/cluster.py:142:80:
  E501 line too long (104 > 99)
ty error: backend/styrmin_backend/services/cluster.py:140:
  Argument of type "None" is not assignable to parameter of type "PodSpec"
```
````

## Notes

- This skill **only** consumes the analyst's machine-readable summary block. It does not re-investigate the issue. If the analyst's hypothesis is wrong, address it by re-running `/bug-analyze` to produce a fresh analyst comment; subsequent `/bug-fix` runs will pick up the most recent valid one.
- The `<short_description>` field of the analyst summary is the load-bearing input for the branch name. The analyze stage validates its kebab-case shape (`^[a-z0-9][a-z0-9-]{0,39}$`) before posting; the fix stage trusts that validation but re-checks the regex defensively in step 2.
- Branch-collision policy is "fail loudly, do not auto-suffix". Auto-suffixing was rejected in research §R5 because it pushes branch-discovery complexity into `bug-test` and `bug-review`.
- The lint-failure path is **the failure path** per FR-010. There is no clearly-flagged-draft-PR variant, no "open the PR with violations and let CI catch it", no "amend and try again silently". The deterministic v1 behaviour is: lint fails → no push, no PR, lint output posted on the issue verbatim.
- Coding-convention questions (where tests live, what command runs the test suite, layered architecture rules, GraphQL regeneration) defer to `AGENTS.md`. Do not duplicate that content here.
- The pipeline works on **any** issue regardless of labels (FR-022). Do not gate on labels.

## Expected Outcome

On success: a new `bug/<NNN>-<short_description>` branch on `origin`, a **draft** pull request against `develop` whose body starts with `Closes #<NNN>` and embeds the analyst summary in a `<details>` block, and an issue comment on issue `<NNN>` ending with `> Next: /bug-test <NNN>`.

On any failure path (missing analyst comment, schema mismatch, branch collision, format/lint failure, or any other irrecoverable error): a comment posted on the issue describing what was attempted and where the stage stopped, **no remote branch**, **no PR**, and **no `> Next:` suggestion**.

In neither case does the skill edit or delete prior comments, and in no case does it auto-fire the next stage.
