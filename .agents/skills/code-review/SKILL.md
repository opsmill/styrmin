---
name: code-review
description: Review the current branch from three perspectives — Product Manager, User, and Senior Engineer — using parallel sub-agents, then aggregate findings into one prioritised summary. Output to the CLI by default, or post as a comment on a GitHub issue when one is supplied.
argument-hint: Optional `<issue>` (bare number like `231` or full URL like `https://github.com/opsmill/styrmin/issues/231`) to post the aggregated report as a comment instead of printing to the CLI.
compatibility: Requires a Git working tree with a feature branch. For the `<issue>` output mode, requires GitHub access via either the `gh` CLI (authenticated) **or** a GitHub MCP server exposing an `add_comment`-equivalent tool. The skill auto-detects which transport is available — do not hard-code one.
---

# Multi-Perspective Branch Review

## Introduction

`code-review` looks at the changes on the current branch through **three independent lenses** and produces a single consolidated recommendation:

- **Product Manager** — Does this deliver the intended value? Is the scope right? Are there roadmap, positioning, or stakeholder risks?
- **User** — Is the resulting behaviour intuitive, discoverable, accessible, and forgiving on the edge cases real users actually hit?
- **Senior Engineer** — Is the code correct, idiomatic, well-tested, secure, performant, and aligned with the project's conventions?

Each lens runs as a **separate sub-agent** so the perspectives do not contaminate each other. The skill then aggregates the three reports into one prioritised action list with explicit ownership tags (PM / UX / ENG).

The skill is transport-agnostic for GitHub writes: it uses `gh` when available, and falls back to a GitHub MCP `add_comment`-equivalent tool when running in a context where `gh` is not. Output to the local CLI is the default and requires no GitHub access at all.

## Arguments

<arguments> $ARGUMENTS </arguments>

**Supported arguments:**

- *(no argument)* — Print the aggregated report to the CLI. Default mode.
- `<issue>` — Either a bare positive integer (e.g. `231`) or a full GitHub issue URL (e.g. `https://github.com/opsmill/styrmin/issues/231`). The aggregated report is posted as a **single comment** on that issue. The CLI also gets a short confirmation with the comment URL.

Anything that does not parse as one of those forms is an error: stop and tell the user the expected format. Do not guess.

## Main Tasks

### 1. Parse arguments and decide output mode

1. If `$ARGUMENTS` is empty / whitespace → **mode = `cli`**. Skip to step 2.
2. Otherwise:
   - If the argument starts with `http`, parse as URL and extract the trailing integer from `/issues/<N>`. If the path segment is `/pull/<N>` or `/pulls/<N>`, accept it but record `kind = pr` (comments on PRs work via the same endpoint).
   - Otherwise treat as a bare integer. Resolve the canonical issue URL by combining with the repo URL from `gh repo view --json url --jq .url` (or the MCP equivalent if `gh` is unavailable).
   - If the result is not a positive integer, **stop and emit a usage message**:

     ```text
     Usage: /code-review [<issue>]

     Argument is optional. When provided, it must be a bare GitHub issue number
     or a full issue URL. Examples:

     - /code-review
     - /code-review 231
     - /code-review https://github.com/opsmill/styrmin/issues/231
     ```

   - Otherwise set **mode = `issue-comment`** and remember `(issue_number, issue_url, kind)`.

### 2. Gather branch context (shared input for every perspective)

Collect the data the three sub-agents will all read. Run these in parallel — they are independent.

1. **Current branch & base.** `git branch --show-current` and `git rev-parse --abbrev-ref HEAD@{upstream} 2>/dev/null || echo "develop"`. If the current branch is `develop`, `stable`, or `main`, **stop**: there is no PR-worthy diff. Tell the user to switch to a feature branch.
2. **Base detection.** Prefer the project's main branch (read from the git status banner at the start of the conversation; the styrmin default is `develop`). Compute `MERGE_BASE=$(git merge-base HEAD <base>)`.
3. **Branch-wide diff.** `git diff --stat $MERGE_BASE..HEAD` for the file list and `git diff $MERGE_BASE..HEAD` for the full patch. Cap the full-patch read at a reasonable size; if the diff is huge, pass file-by-file summaries to the sub-agents instead of the raw blob.
4. **Commits on the branch.** `git log --oneline $MERGE_BASE..HEAD`.
5. **Linked issue / PR description (if any).** Look for `Closes #N` / `Fixes #N` lines in recent commit messages or in the PR body if a PR already exists (`gh pr view --json body,title,number 2>/dev/null` — non-fatal if no PR yet).
6. **Project conventions to load once and pass through.** `AGENTS.md`, the per-component `AGENTS.md` files for the directories the diff touches (`backend/AGENTS.md`, `frontend/AGENTS.md`, `python_sdk/AGENTS.md`), and any relevant ADRs in `dev/adr/` referenced by the changed files.

Bundle this into a **shared briefing string** the three sub-agents receive verbatim. Do not let any single perspective re-derive it — they must all reason about the same diff.

### 3. Launch the three perspective sub-agents in parallel

Use the `Agent` tool to launch all three in a **single message with three tool-use blocks** so they run concurrently. Each sub-agent gets:

- The shared briefing string from step 2 (branch name, base, file list, full diff or per-file summary, commit log, linked issue, conventions).
- A perspective-specific prompt (below) — written so the agent stays in character and does not drift into the other lenses.
- A response format requirement: each agent **must** return a short structured report with the sections listed under "Sub-agent response format" further down.

Pick `subagent_type = "general-purpose"` for all three unless the project defines specialised agents for these roles — do not invent agent types that are not in the available list.

#### 3a. Product Manager perspective

Brief the PM agent with the following:

> You are a **Product Manager** reviewing a feature branch that is about to become a pull request. Your goal is **not** to judge code quality — leave that to engineering. Focus on:
>
> 1. **Value delivered.** Does this change advance a user goal, a customer commitment, a roadmap item, or a measurable KPI? Cite specifics from the diff and the linked issue (if any). If you cannot articulate the user-visible value in one sentence, flag it.
> 2. **Scope discipline.** Is the diff doing one thing, or has scope crept? Are there changes that should be split out into a follow-up? Are there changes the issue/spec promised that are *missing*?
> 3. **Positioning & risk.** Does this conflict with anything else on the roadmap, any active experiment, an upcoming launch, or a deprecation? Are there stakeholders (support, sales, docs, legal) who need a heads-up?
> 4. **Rollout & comms.** Will users notice this? If yes, is there a changelog entry, docs update, or in-product comms? If a feature flag is appropriate, is one present?
> 5. **Success metric.** How will we know this worked? Is there instrumentation, an analytics event, or a measurable outcome?
>
> Return your findings in the structured format below. Be specific — cite filenames and line ranges where they justify a point. Do not propose code-level fixes; propose product-level fixes.

#### 3b. User perspective

Brief the User agent with the following:

> You are a **representative end user** of the product. Walk through the change as a user would. You do not have access to the team's roadmap or internal language. Focus on:
>
> 1. **Discoverability & first-use.** If you encountered this for the first time, would you know it exists? Would you know how to invoke it? Are the labels, copy, and affordances clear?
> 2. **Flow & friction.** Is the new behaviour intuitive end-to-end, or are there extra clicks, surprising modal dialogs, confusing state transitions, or required fields that are unclear?
> 3. **Edge cases real users hit.** Empty states. Long values. Slow networks. Mid-action errors. Permissions denials. Disabled-but-present buttons. Unicode / RTL / very-long-name inputs.
> 4. **Error & recovery.** When something goes wrong, does the message tell the user *what happened* and *what to do next*? Or does it surface an internal stack trace / opaque error code?
> 5. **Accessibility.** Keyboard navigation, screen-reader labels, colour-only signalling, focus management, contrast — only call out what the diff actually changes or introduces.
> 6. **Performance perception.** Loading states, optimistic updates, perceived responsiveness for the slowest realistic case.
>
> Return your findings in the structured format below. Cite the file or component where the user-visible behaviour lives. Do not propose code-level fixes; propose user-experience fixes.

#### 3c. Senior Engineer perspective

Brief the Senior Engineer agent with the following:

> You are a **Senior Software Engineer** doing a thorough technical review of this branch. Focus on:
>
> 1. **Correctness.** Does the code actually do what the commits claim? Spot bugs, off-by-ones, race conditions, swallowed exceptions, missing awaits, leaked resources.
> 2. **Architecture & boundaries.** Does the change respect module boundaries documented in `AGENTS.md` / per-component `AGENTS.md`? Are there leaky abstractions, circular imports, or violated layering?
> 3. **Tests.** Is coverage proportionate to risk? Are tests asserting behaviour or implementation? Per the project's "Always Do" list, is there E2E coverage for any new user-visible flow, and a propagation test for any GraphQL schema change?
> 4. **Security & data handling.** Input validation, authz checks, secret exposure, injection surfaces, PII handling, logging hygiene.
> 5. **Performance.** N+1 queries, unbounded loops, missing indexes, synchronous calls on the request path, memory growth.
> 6. **Maintainability.** Naming, dead code, repeated patterns ripe for extraction *only* if extraction reduces complexity, comment rot, premature abstraction, magic numbers.
> 7. **Conventions & tooling.** Linting / formatting / type-check posture, generated-file freshness (GraphQL schema, SDK types), conventional-commit messages on the branch, no `--no-verify` smell.
>
> Return your findings in the structured format below. Cite `path:line` for every concrete observation. Prefer concrete, actionable suggestions over abstract complaints.

#### Sub-agent response format (required from every perspective)

Tell every sub-agent to respond with **exactly** this Markdown structure so aggregation is mechanical:

```markdown
### Headline

<one sentence: the single most important thing this perspective wants the author to hear>

### Critical (must address before merge)

- [path:line] <observation> — <recommendation>
- …

### Important (should address)

- [path:line] <observation> — <recommendation>
- …

### Suggestions (nice to have)

- [path:line] <observation> — <recommendation>
- …

### Strengths

- <what this perspective explicitly liked>
- …
```

Any section can be empty (`- _(none)_`). Critical/Important/Suggestions categorisation is the agent's judgement call.

### 4. Aggregate the three reports

Once all three agents return, build a **single consolidated report** with the structure below. Do not paraphrase the agents' findings — preserve their language. Just merge, deduplicate, and tag.

Deduplication rule: if two perspectives flag the same concrete issue (same file:line or same observable behaviour), keep the more specific phrasing and merge the tags (e.g. `[ENG + UX]`). Do not silently drop the other perspective's framing if it adds information — keep it as a sub-bullet.

Severity precedence on overlap: if perspectives disagree on severity, take the **highest** severity any perspective assigned. Note the disagreement in parentheses if it is meaningful (e.g. "(ENG: Critical, PM: Suggestion)").

Final report template:

```markdown
# Branch Review — Multi-Perspective

**Branch:** `<branch>`  **Base:** `<base>`  **Commits:** N  **Files changed:** N

## TL;DR

- **PM headline:** <PM agent's headline>
- **UX headline:** <User agent's headline>
- **ENG headline:** <Senior Engineer agent's headline>

## Recommended action plan (do these in order)

1. **[CRITICAL] [TAGS]** <merged observation> — <recommendation>
2. **[CRITICAL] [TAGS]** …
3. **[IMPORTANT] [TAGS]** …
4. **[SUGGESTION] [TAGS]** …

## Findings by perspective

### Product Manager
<verbatim PM report>

### User
<verbatim User report>

### Senior Engineer
<verbatim Senior Engineer report>

## Strengths (consensus)

- <items flagged as strengths by ≥2 perspectives, or by 1 with strong wording>
```

`[TAGS]` is one or more of `PM`, `UX`, `ENG`, joined with `+` (e.g. `[ENG + UX]`). The action-plan section is the **value-add** of this skill over running three reviews independently — order matters and overlapping findings get consolidated.

### 5. Emit the report (output mode)

#### 5a. `cli` mode (default)

Print the full aggregated report directly to the conversation. No file is written. No GitHub call is made. Stop after printing.

#### 5b. `issue-comment` mode

Post the aggregated report as a **single comment** on the supplied issue (or PR — same endpoint). The skill must work with **either** transport — pick whichever is available at runtime; do not require both:

1. **Prefer `gh` CLI if available.** Detect with `command -v gh && gh auth status` (treat a non-zero exit on either as "not available").
   - Issue: `gh issue comment <N> --body-file <tmpfile>`
   - PR (when `kind = pr`): `gh pr comment <N> --body-file <tmpfile>`
2. **Fall back to GitHub MCP** if `gh` is unavailable. Look for an MCP tool whose name matches `*add*comment*` or `*create*comment*` on a server exposing GitHub resources (`mcp__*github*` or similar). Pass `owner`, `repo`, `issue_number` (or `pull_number`), and `body`. Do not hard-code a specific MCP server name — discover at runtime.
3. **If neither transport is available**, do **not** silently downgrade to CLI mode. Stop and tell the user that `<issue>` output mode requires either an authenticated `gh` CLI or a GitHub MCP server exposing a comment-creation tool, and suggest re-running without the argument for CLI output.

After a successful post, also print a one-line confirmation to the CLI with the comment URL (the comment URL is returned by `gh` as stdout; the MCP tool typically returns it in the response payload).

The comment body is the **full** aggregated report from step 4 — do not abbreviate it. The intent is that the issue thread captures the whole review so anyone arriving later has the full context.

### 6. Failure paths

- **Diff is empty** (branch is fully merged or identical to base): stop and tell the user there is nothing to review on this branch.
- **A sub-agent fails or times out**: do **not** silently drop its perspective. Emit the aggregated report with a clearly marked section for the missing perspective (e.g. `### Product Manager\n\n_⚠️ The PM perspective failed: <reason>. Re-run the skill or invoke the PM lens directly._`). Critically: still emit something — the other two perspectives are valuable on their own.
- **Comment post fails in `issue-comment` mode**: print the full aggregated report to the CLI anyway (so the work is not lost), then surface the post error so the user can retry manually.

## Notes

- **Sub-agents must run in parallel.** Three sequential agents triple the wall-clock time for no benefit, since they read the same diff. Always send the three `Agent` tool calls in a single message.
- **Perspective isolation matters.** Do not summarise one agent's output into another agent's brief — it defeats the purpose of independent lenses. Each agent gets only the shared briefing string plus its own prompt.
- **Transport-agnostic by design.** The `<issue>` output path must keep working in both local-CLI execution (where `gh` is typical) and MCP-only execution (where there is no shell). Discovery happens at runtime; the skill stays the same.
- **This skill never modifies the branch.** It does not commit, push, open a PR, or transition any PR state. The only side effect, when `<issue>` is provided, is a single new comment on the supplied issue.
- **This skill is distinct from `/speckit-review` and `/bug-review`.** `speckit-review` aggregates six *engineering* sub-aspects; `bug-review` is a pipeline-aware draft → ready gate. `code-review` covers product, user, and engineering at once and is intended for any feature branch — not just bugs and not just spec-kit features.

## Expected Outcome

**CLI mode:** the aggregated multi-perspective report is printed to the conversation, with a prioritised action plan at the top and verbatim per-perspective reports below. No GitHub side effects, no files written.

**Issue-comment mode:** the same aggregated report is posted as a single new comment on the supplied issue or PR, and a one-line confirmation with the comment URL is printed to the CLI. The branch, the working tree, and any existing PR state are untouched.

**On any sub-agent failure:** the report is still emitted with the failed perspective explicitly marked as missing, so the surviving perspectives reach the user. On post-failure in issue-comment mode, the report is printed to the CLI as a fallback so the analysis is preserved.
