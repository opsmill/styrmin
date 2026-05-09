---
name: bug-analyze
description: Investigate a reported bug and post a structured analyst comment on the issue with a hypothesis, affected files, reproduction steps, and a machine-readable summary block for downstream pipeline stages.
argument-hint: Issue number or full GitHub issue URL (e.g., `206` or `https://github.com/opsmill/styrmin/issues/206`)
compatibility: Requires GitHub access (`gh` CLI authenticated, or equivalent GitHub MCP/API tooling) and write access to the target repository's issues.
---

# Bug Pipeline — Analyze

## Introduction

`bug-analyze` is the first of four stages in the bug-fixing pipeline (`bug-analyze` → `bug-fix` → `bug-test` → `bug-review`). It produces the structured first-pass investigation that every downstream stage consumes: a root-cause hypothesis, a list of suspect files, reproduction steps, and a fenced YAML "machine-readable summary" block bracketed by stable HTML comment markers so the fix stage can locate it without fuzzy matching.

The skill is runnable two ways with **identical** observable side effects:

- Locally from the Claude Code CLI: `/bug-analyze <issue>`.
- From the GitHub UI by typing `/bug-analyze <issue>` as an issue comment, which fires the matching `bug-agent-analyst.yml` workflow.

Stages chain via a hybrid model — every stage is human-triggered, and on success the closing line of this skill's output comment names the next command. This skill never auto-fires the next stage.

## Prerequisites

- `gh` CLI authenticated against the target repository (or equivalent GitHub MCP/API tooling available to the agent).
- Write access to issues on the target repository (needed to post the analyst comment).
- A working tree of the repository so the agent can search the codebase while forming a hypothesis.

## Arguments

<arguments> $ARGUMENTS </arguments>

The argument is a reference to a GitHub issue, accepted in either form:

- **Bare integer**: `206` — resolved against the current repository.
- **Full URL**: `https://github.com/opsmill/styrmin/issues/206` — the issue number is extracted from the path.

Both forms canonicalise to the same `(number, url)` pair internally and produce the same result.

## Main Tasks

### 1. Normalise the argument

Per the slash-command protocol, every stage that takes an issue argument MUST accept either form and normalise both to a canonical `(number, url)` pair.

1. If `$ARGUMENTS` is empty or contains only whitespace, **stop and post a usage comment** (see step 7). Do not guess a value, and do not perform any other side effect.
2. If the argument starts with `http`, parse it as a URL and extract the trailing integer from `/issues/<N>` (or `/pull/<N>`).
3. Otherwise, treat the argument as a bare numeric identifier. Resolve the canonical URL by combining it with the repo URL from `gh repo view --json url --jq .url`.
4. If the result is not a positive integer, treat the input as malformed and post the usage comment per step 7. Do not proceed.

### 2. Fetch the issue context

Pull both the body and the existing comments — they are the basis for the investigation.

```bash
gh issue view <NNN> --json number,url,title,body,comments
```

Read the body carefully. Skim existing comments for additional reproduction details, prior maintainer notes, or earlier analyst attempts on the same issue.

### 3. Investigate the codebase

Form a hypothesis grounded in the issue text and the actual repository state.

1. Pull keywords from the issue body (error messages, file paths, component names, command lines, identifier fragments).
2. Search the codebase for those keywords. Read the call sites and surrounding context — do not fabricate a hypothesis from skimming filenames alone.
3. Identify the **specific** files most likely to contain the defect. Repo-relative paths only.
4. Reconstruct reproduction steps from the issue body (preferred) or from your code reading. Each step should be a single-line shell command, action description, or expected observation.

This skill **does not** duplicate project coding-conventions content. Defer all questions about how the code is structured, where tests live, what command runs the test suite, and how the layered architecture is organised to the existing `AGENTS.md` files (root + per-component). Read those if you need them; do not paraphrase them here.

### 4. Decide success or failure

If you cannot form a defensible hypothesis — for example, the issue lacks reproduction information, or the keywords match nothing meaningful in the codebase, or you have only conjecture left — proceed to the **failure path** in step 6.

Otherwise, proceed to the **success path** in step 5.

### 5. Compose the success comment

Post a single comment on the issue. The comment has prose sections followed by the closing YAML summary block.

**Prose sections** (in order):

- **Hypothesis** — one paragraph describing the suspected root cause in plain language.
- **Affected files** — bulleted list of repo-relative paths. State briefly why each is suspect.
- **Reproduction steps** — numbered or bulleted list, derived from the issue body and/or your reading.

**Closing YAML summary block.** This is the contract with the fix stage and MUST conform exactly to `specs/010-bug-pipeline-skills/contracts/analyst-summary-schema.md` (schema version 1). The fenced block MUST:

- Be the **last** structured element in the comment (after all prose).
- Use the `yaml` language tag for syntax highlighting.
- Be wrapped on its own lines by the markers `<!-- bug-pipeline:summary:start -->` and `<!-- bug-pipeline:summary:end -->` exactly as shown — these are the stable anchors downstream stages match.

Schema reference (do not deviate from key names, types, or structure):

```yaml
schema_version: 1
issue:
  number: <NNN>
  url: <canonical issue URL>
hypothesis: |
  One paragraph describing the suspected root cause in plain language. May span
  multiple lines using YAML block-literal syntax.
affected_files:
  - <repo-relative path 1>
  - <repo-relative path 2>
reproduction:
  - "<single-line step 1>"
  - "<single-line step 2>"
short_description: <kebab-case fragment, ^[a-z0-9][a-z0-9-]{0,39}$>
next_command: /bug-fix <NNN>
```

Field rules:

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `schema_version` | integer | yes | Always `1` for this skill version. |
| `issue.number` | integer | yes | Positive; matches the issue the comment is posted on. |
| `issue.url` | string | yes | Canonical GitHub URL. |
| `hypothesis` | string | yes | ≥ 1 sentence; ≤ ~500 chars. Use YAML block-literal (`\|`) for multi-line. |
| `affected_files` | list of strings | yes | Repo-relative paths. May be `[]` if localisation failed (a soft signal to the fix stage to widen its search). |
| `reproduction` | list of strings | yes | At least 1 step. |
| `short_description` | string | yes | Kebab-case, matches `^[a-z0-9][a-z0-9-]{0,39}$`. Used by the fix stage to derive the branch name `bug/<NNN>-<short_description>`. |
| `next_command` | string | yes on success | Always `/bug-fix <NNN>` for this stage. **Omitted on failure.** |

After the closing `<!-- bug-pipeline:summary:end -->` marker, end the comment with a blank line and a final line:

```text
> Next: `/bug-fix <NNN>`
```

Post the comment with `gh issue comment <NNN> --body-file <path>` (or the equivalent MCP/API call). Do **not** edit or delete prior comments — every stage appends.

### 6. Compose the failure comment (no defensible hypothesis)

If you cannot form a defensible hypothesis, post a prose-only comment that:

- Names what was investigated (which keywords, which files read, which existing comments consulted).
- States plainly where the analysis stopped and why (e.g., reproduction steps missing, keywords matched no plausible call site, conflicting reports across comments).

The failure comment MUST:

- **Omit** the YAML summary block entirely. Do not post an empty or placeholder block.
- **Omit** the `> Next:` suggestion line. Failure paths never suggest a next stage.

The maintainer can address the gap (e.g., ask the reporter for a reproduction) and re-run `/bug-analyze` later; subsequent successful runs supersede earlier failures because consumers always pick the most recent valid analyst comment.

### 7. Handle missing or invalid arguments

Per `specs/010-bug-pipeline-skills/contracts/slash-command-protocol.md`, when triggered with no argument, an empty argument, or an argument that does not parse as a positive integer or canonical GitHub URL, the skill MUST:

1. Post a comment on the same issue/PR explaining the expected argument format and giving an example.
2. Stop without performing any other side effects (no further investigation, no second comment).

Suggested usage-comment body:

```text
Usage: `/bug-analyze <issue>`

Argument is required and must be either a bare issue number or a full GitHub issue URL. Examples:

- `/bug-analyze 206`
- `/bug-analyze https://github.com/opsmill/styrmin/issues/206`
```

## Examples

**Success comment** (truncated; ≤20 lines):

```markdown
### Hypothesis

The cluster reconciler crashes when the manifest's `spec` field is empty because
`build_pod_template` dereferences `spec.containers[0]` without a guard.

### Affected files

- `backend/styrmin_backend/services/cluster.py` — `build_pod_template` entry point.
- `backend/styrmin_backend/api/schema/cluster.py` — input validation likely missing.

### Reproduction

1. Apply the manifest from the issue's reproduction section.
2. Run `kubectl get pods -n styrmin-test`.
3. Observe pod stuck in `CrashLoopBackOff`.

<!-- bug-pipeline:summary:start -->
```yaml
schema_version: 1
issue: { number: 206, url: https://github.com/opsmill/styrmin/issues/206 }
hypothesis: "build_pod_template dereferences spec.containers[0] with no guard"
affected_files:
  - backend/styrmin_backend/services/cluster.py
  - backend/styrmin_backend/api/schema/cluster.py
reproduction:
  - "Apply the manifest from the issue's reproduction section"
  - "Run `kubectl get pods -n styrmin-test`"
  - "Observe the pod is stuck in CrashLoopBackOff"
short_description: cluster-pod-crashloop-on-empty-spec
next_command: /bug-fix 206
```
<!-- bug-pipeline:summary:end -->

> Next: `/bug-fix 206`
```

**Failure comment** (truncated; ≤20 lines):

```markdown
### Analysis stopped — insufficient information

I searched the codebase for the keywords from the issue body
(`reconciler`, `CrashLoopBackOff`, `manifest spec`) and read
`backend/styrmin_backend/services/cluster.py` and the issue's
two existing comments.

The reported failure has no reproduction steps, no example
manifest, and the keyword matches in the codebase span three
unrelated subsystems. I cannot pick one root-cause hypothesis
without guessing.

To unblock: please add a reproduction (manifest + commands +
observed vs expected output) to the issue, then re-run
`/bug-analyze`.
```

## Notes

- This skill **only** posts a comment. It never creates branches, opens PRs, edits prior comments, or invokes downstream stages.
- The YAML summary block is the contract with `bug-fix`. Any field rename, type change, or marker change is a breaking change to the inter-stage contract — coordinate via `specs/010-bug-pipeline-skills/contracts/analyst-summary-schema.md` before deviating.
- The pipeline works on **any** issue regardless of labels (FR-022). Do not gate on labels.
- Coding-convention questions (where tests live, what command runs the test suite, layered architecture rules) defer to `AGENTS.md`. Do not duplicate that content here.

## Expected Outcome

A single comment posted on the target issue, containing either:

- **Success**: prose Hypothesis / Affected files / Reproduction sections, a closing YAML summary block bracketed by the `<!-- bug-pipeline:summary:start -->` / `:end -->` markers and conforming to schema version 1, and a final `> Next: /bug-fix <NNN>` suggestion line.
- **Failure**: a prose-only comment naming what was investigated and where analysis stopped, with **no** YAML block and **no** next-stage suggestion.

In either case, no other side effects (no branches, no PRs, no comment edits).
