# Phase 1 Data Model: Bug-Fixing Pipeline as Skills with GHAW Thin Wrappers

This feature does not introduce any database tables, GraphQL types, or persistent data structures. The "data model" here is the set of **observable artefacts** that flow between stages — all of which live in GitHub.

## Entities

### 1. Bug-issue argument (input)

The user-supplied reference identifying the target issue or PR.

| Field | Type | Notes |
|-------|------|-------|
| `raw` | string | What the user typed: `206` or `https://github.com/opsmill/styrmin/issues/206` |
| `number` | integer | Issue/PR number, derived |
| `url` | string | Canonical URL, derived |
| `kind` | enum: `issue` \| `pull_request` | Inferred from URL path or context (the test/review stages accept PR refs) |

**Validation**: `raw` is non-empty; `number` parses as a positive integer; `url` matches `https://github.com/<owner>/<repo>/(issues|pull)/<number>`.

**State transitions**: none — the argument is read once at stage entry.

### 2. Analyst summary block (inter-stage contract)

A fenced YAML block embedded in the analyst's issue comment. Contract documented in `contracts/analyst-summary-schema.md`.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `schema_version` | integer | yes | `1` for v1 of this feature |
| `issue.number` | integer | yes | Source issue number |
| `issue.url` | string | yes | Source issue canonical URL |
| `hypothesis` | string | yes | One-paragraph root-cause hypothesis |
| `affected_files` | list[string] | yes | Repo-relative paths (may be empty if the analyst could not localise) |
| `reproduction` | list[string] | yes | Ordered reproduction steps |
| `short_description` | string | yes | Kebab-case fragment for the fix branch name (≤40 chars) |
| `next_command` | string | yes (on success) | Suggested next slash command, e.g. `/bug-fix 206` — absent on failure |

**State transitions**: 
- The block is **emitted once** by the analyst at the end of a successful run.
- It is **read** by the fix stage (most recent matching block on the issue), and transitively referenced by the test stage (via the PR description's `<details>` block).

### 3. Fix branch (git artefact)

A git branch produced by the fix stage and amended by the test stage.

| Field | Type | Notes |
|-------|------|-------|
| `name` | string | Format: `bug/<NNN>-<short_description>` |
| `base` | string | The default branch at fix-stage runtime (e.g., `develop`) |
| `commits` | sequence | Fix commits from the fix stage; test commits added by the test stage |

**Lifecycle**: created by `bug-fix`, extended by `bug-test`, **never** deleted by the pipeline (humans manage cleanup post-merge or post-abandonment).

**Collision rule**: if a branch with the target `name` already exists, the fix stage fails (see research R5).

### 4. Pipeline draft PR (GitHub artefact)

The pull request opened by the fix stage.

| Field | Type | Notes |
|-------|------|-------|
| `branch` | string | The fix-branch `name` (same value as entity 3) |
| `state` | enum: `draft` \| `ready_for_review` | Starts `draft`; flipped by review stage on pass |
| `body` | string | Follows the PR description template documented in research R6 |
| `closes_ref` | string | `Closes #<NNN>` line in body — required (FR-011a) |

**State transitions**: 
- `draft` (created by fix) → still `draft` (test extends commits) → `ready_for_review` (review passes) **or** `draft` (review keeps it draft).
- A human reviewer can manually flip back to `draft`; subsequent `/bug-review` runs respect the current state.

### 5. Stage output comment (GitHub artefact)

A comment posted by each stage on the issue (analyze) or PR (test, review).

| Field | Type | Notes |
|-------|------|-------|
| `target` | enum: `issue` \| `pr` | Determined by stage (analyze → issue; test/review → PR; fix posts only on failure → issue) |
| `body` | string | Stage-specific structured prose |
| `next_command_suggestion` | string \| null | Trailing line on success; null on failure |
| `summary_block` | YAML \| null | Present only on the analyst's success comment |

**State transitions**: append-only — the pipeline never edits or deletes comments.

## Relationships

```text
                      ┌──────────────────────┐
                      │ Bug-issue argument   │
                      └──────────┬───────────┘
                                 │ (input to every stage)
                                 ▼
   ┌──────────────────────┐      ┌──────────────────────┐
   │ analyze stage        │ ───▶ │ Analyst summary block│
   │ (writes issue        │      │ (in issue comment)   │
   │  comment + summary)  │      └──────────┬───────────┘
   └──────────────────────┘                 │ (read by fix)
                                            ▼
                                ┌──────────────────────┐
                                │ Fix branch + draft PR│
                                │ (PR body embeds the   │
                                │  summary in <details>)│
                                └──────────┬───────────┘
                                           │ (test pushes commits to same branch)
                                           ▼
                                ┌──────────────────────┐
                                │ Test commits + PR    │
                                │ summary comment      │
                                └──────────┬───────────┘
                                           │ (review reads PR + tests)
                                           ▼
                                ┌──────────────────────┐
                                │ Review comment +     │
                                │ PR state transition  │
                                └──────────────────────┘
```

## Validation rules at stage boundaries

| Boundary | Validation |
|----------|------------|
| analyze entry | `raw` argument is non-empty; issue exists and is readable. |
| analyze exit (success) | Comment posted; YAML block parses; `schema_version=1`; all required fields present. |
| fix entry | At least one analyst comment with a parseable `schema_version=1` block exists on the issue. |
| fix exit (success) | Branch named `bug/<NNN>-<short_description>` exists on remote; draft PR open; `Closes #<NNN>` present in body; analyst block embedded in `<details>`. |
| test entry | An open draft PR linked to the issue exists; its branch matches the fix-branch convention. |
| test exit (success) | New commits on the same branch; project test command passes when run on that branch. |
| review entry | An open draft PR linked to the issue exists. |
| review exit | Review comment posted; PR state is consistent with the verdict (ready-for-review iff satisfied; draft otherwise). |
