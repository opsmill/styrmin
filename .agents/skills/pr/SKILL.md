---
name: pr
description: Take the current branch through to an open, CI-monitored pull request — branch discipline, branch-wide change analysis, doc updates, and required user approval at each step.
argument-hint: Optional `commit` to stage, commit, and push uncommitted changes before opening the PR
compatibility: Requires a Git working tree, GitHub access (gh CLI authenticated, GitHub MCP server, or equivalent), and the Styrmin repo layout for documentation cross-references.
metadata:
  source: .agents/commands/pr.md
---

# Open Pull Request

## Introduction

Handle the full workflow from current branch state to an open, CI-monitored pull request. This skill enforces branch discipline, analyzes all branch changes for a business-value-focused description, ensures documentation is current, and requires user approval at every step.

## Arguments

<arguments> $ARGUMENTS </arguments>

**Supported arguments:**

- `commit` — Stage, commit, and push uncommitted changes before proceeding. **Without this argument, no commits are made** — the skill works only with what is already committed on the branch.

## Main Tasks

### 1. Safety Checks & Branch State

First, verify the agent is on a safe branch and understand the current git state. Branch creation and commit logic are owned by the `commit` skill — this phase only inspects state and decides what to do next.

1. Run `git status` to see uncommitted/staged/untracked files.
2. Run `git branch --show-current` to identify the current branch.
3. **If on `develop`, `stable`, or `main`:**
   - **If `commit` was passed:** proceed to Phase 2; the `commit` skill will refuse the protected branch, propose a feature branch name (`NNN-short-name` when changes match a `specs/` directory, otherwise `dga-short-description`), and ask the user for approval before creating it. Do not pre-create the branch here — let the `commit` skill own that conversation so the rules stay in one place.
   - **If `commit` was NOT passed:** STOP. There's no feature branch to open a PR from. Tell the user they need to either invoke `/pr commit` (so the `commit` skill creates a branch and captures the changes), or switch to a feature branch first.
4. If already on a feature branch, continue to the next phase.

### 2. Commit Changes (only when `commit` argument is provided)

**Skip this phase entirely if `commit` was NOT passed as an argument.** If there are uncommitted changes and `commit` was not provided, warn the user that uncommitted changes exist but will not be included in the PR.

When `commit` IS provided, run the project-specific prep here in `pr` (because it depends on Styrmin's toolchain), then delegate the actual commit + push to the `commit` skill so branch discipline, secret hygiene, and message conventions stay in one place:

1. Run formatters and linters first (required by project conventions):

   ```bash
   uv run invoke format lint
   ```

2. Check if any GraphQL schema files (under `backend/styrmin_backend/api/schema/`) or `.graphql` query files were modified. If so, regenerate and re-stage the regenerated artefacts:

   ```bash
   uv run styrmin export graphql-schema schema.graphql
   uv run invoke generate
   ```

3. Invoke the `commit` skill with the `push` argument: `/commit push`. The skill will:
   - Refuse to commit on `develop` / `stable` / `main` and, if needed, propose a feature branch name (spec-prefixed or `dga-…`) for user approval before creating it via `git checkout -b`.
   - Stage changes safely (explicit paths, secret-pattern warnings).
   - Draft a conventional-commit message and confirm it with the user.
   - Run pre-commit hooks (no `--no-verify`); fix violations and create a new commit on hook failure.
   - Push the branch upstream (`git push -u origin <branch>` on first push).

   Do not duplicate any of that logic inline here. If the user has additional commit-message guidance specific to this PR (e.g., spec reference, conventional-commit scope), pass it along when invoking the skill.

4. After `/commit push` returns, confirm the working tree is clean and the branch is published before continuing to Phase 3.

### 3. Analyze All Branch Changes

Understand the FULL scope of changes in this branch — not just the latest commit, but everything since it diverged from develop. If there's a related spec, use it to understand the business context.

1. Determine the base branch (default: `develop`).
2. View all commits in the branch:

   ```bash
   git log develop..HEAD --oneline
   ```

3. View the full diff of all changes:

   ```bash
   git diff develop...HEAD --stat
   git diff develop...HEAD
   ```

4. **Check for a related spec:** If the branch name matches a spec directory in `specs/` (e.g., branch `058-frontend-testing` → `specs/058-frontend-testing/`):
   - Read `spec.md` to understand user scenarios, functional requirements, and success criteria.
   - This is the primary source for framing the PR's business value.
5. Categorize changes by area: backend, frontend, documentation, CI/CD, specs, configuration.

### 4. Documentation Review

Before opening the PR, ensure that developer documentation in `dev/` reflects the changes being introduced. Stale docs are worse than no docs.

1. Based on the changes identified in Phase 3, check relevant documentation:

   | If changes touch... | Check these docs |
   |---------------------|-----------------|
   | API routes/resolvers | `dev/knowledge/backend/api.md` |
   | Data models/migrations | `dev/knowledge/backend/data-models.md` |
   | Services layer | `dev/knowledge/backend/services.md` |
   | Orchestration/Prefect flows | `dev/knowledge/backend/orchestration-flows.md` |
   | Hooks/actions | `dev/knowledge/backend/hooks-and-actions.md` |
   | Reconciliation | `dev/knowledge/backend/reconciliation.md` |
   | Agent/K8s agent | `dev/knowledge/backend/agent.md` |
   | Backup/restore | `dev/knowledge/backend/backup-restore.md` |
   | E2E tests | `dev/knowledge/backend/e2e-testing.md` |
   | Frontend | Check if frontend knowledge docs exist; propose creating them if not |
   | New developer workflows | `dev/guides/` |

2. For each relevant doc:
   - Read it and compare against the actual changes.
   - If the doc is outdated or missing coverage of new functionality, propose updates.
   - Present proposed doc changes to the user for approval.
3. Commit any doc updates to the branch (with a `docs:` conventional commit).
4. Push if new commits were added.

### 5. Draft PR Description

Focus on business value — what problem does this solve, what capability does it add? The reviewer should understand WHY before they look at HOW. Reference the spec if one exists.

**PR Title:** Short, conventional format (under 70 chars). Examples:

- `feat: add environment backup and restore operations`
- `fix: resolve cluster config drift during reconciliation`
- `refactor: migrate inline GraphQL queries to dedicated files`

**PR Body Template:**

```markdown
## Summary
[1-3 sentences: what business problem this solves or what capability it adds.
Frame as outcomes for users/operators, not as code changes.]

## Key Changes
[Bulleted list of the most important changes, framed as outcomes:
- "Operators can now back up and restore environments" NOT "Added backup_service.py"
- "GraphQL queries are validated against the schema in CI" NOT "Moved queries to .graphql files"]

## Spec Reference
[If tied to a spec: link to specs/NNN-name/spec.md, highlight key requirements addressed.
Omit this section if no spec exists.]

## Documentation Updates
[List any dev/ docs that were added or updated as part of this PR.
Omit this section if no docs were changed.]

## Test Plan
[How to verify — test commands to run, manual verification steps, or CI checks to watch]
```

**Labels:** Choose from repo labels (e.g., `gh label list`). Common ones:

- `type: enhancement`, `type: bug`, `type: tech-debt`, `type: housekeeping`, `type: documentation`
- `claude-code-assisted`

### 6. User Validation & PR Creation

**IMPORTANT: Always present the full PR draft to the user for review BEFORE creating it.** Never create a PR without explicit user approval.

1. Present to the user:
   - PR title
   - PR body (rendered)
   - Target base branch
   - Labels
2. Wait for the user's explicit approval or requested changes.
3. After approval, create the PR using the GitHub interface available to the agent. Examples:

   ```bash
   gh pr create --title "[TITLE]" --body "[BODY]" --base develop --label "[LABELS]"
   ```

   Or, when using the GitHub MCP server, the equivalent `create_pull_request` call.
4. Return the PR URL to the user.

### 7. Hand Off to `pr-monitor` as a Background Survey Agent

Don't just open the PR and walk away — but don't re-implement the CI babysitting loop here either, and don't sit blocked in the foreground waiting 30+ minutes for E2E to finish. The `pr-monitor` skill owns the CI workflow (poll, classify, reproduce narrowly, fix, retry up to 5 times, revert on exhaustion), and CI watching is the textbook "long-running, independent of what the user does next" survey task. Spawn it as a background agent so the parent conversation can return control to the user immediately.

1. Confirm the PR was created and you have the PR number / URL / branch name.
2. **Spawn `pr-monitor` as a background survey agent.** Use the runtime's agent-launching mechanism (Claude Code: the `Agent` tool with `run_in_background: true`; other runtimes: equivalent background-task primitive). The agent must run with a clean context — give it everything it needs in the prompt rather than relying on parent-conversation state.

   Recommended invocation (Claude Code, general-purpose subagent):

   ```text
   Agent(
     description: "Monitor PR #<N> CI",
     subagent_type: "general-purpose",
     run_in_background: true,
     prompt: "Run the workflow defined in .agents/skills/pr-monitor/SKILL.md
              against PR #<N> on branch <branch>. The PR was just opened by
              the /pr skill at commit <sha>; treat that commit as the
              baseline_commit for the revert-on-exhaustion logic. Follow
              every phase of SKILL.md verbatim, including the narrow-
              reproduction-first discipline and the 5-iteration cap.
              Produce the SKILL.md final report when you finish."
   )
   ```

   Adjust the prompt to match your runtime's agent contract, but always (a) name the SKILL.md file as the source of truth, (b) pass the PR number, branch, and baseline commit, and (c) require the SKILL.md final report on completion.

3. **Tell the user what just happened**, then return control:
   - PR URL.
   - That `pr-monitor` is now running in the background as a survey agent.
   - That CI feedback / fix attempts / a final report will arrive asynchronously when the agent completes.

   Do not poll or re-summarize CI here. The agent's final report is the closing status; surface it to the user when it lands.

If the runtime cannot spawn background agents, fall back to invoking `/pr-monitor <pr-number>` synchronously, or — as a last resort — poll `gh run list --branch <branch-name>` every 30–60 seconds and follow the same narrow-reproduction-first discipline `pr-monitor` enforces. Do not push speculative fixes when local reproduction is possible.

## Notes

**Branch Safety:**

- This skill will NEVER commit to `develop` or `main`.
- If uncommitted changes exist and `commit` was not passed, warn but do not commit.

**Business Value Focus:**

- PR descriptions should answer "why does this matter?" before "what changed?".
- When a spec exists, it is the primary framing device — reference user scenarios and success criteria.
- Technical implementation details belong in the diff, not the PR description.

**Documentation Discipline:**

- Stale docs are worse than no docs — always check before opening a PR.
- New features or changed behavior should be reflected in `dev/knowledge/` or `dev/guides/`.

## Expected Outcome

A pull request that:

- Lives on a properly named feature branch (never `develop` or `main`).
- Has a business-value-focused description referencing specs when available.
- Includes up-to-date developer documentation.
- Has been reviewed and approved by the user before creation.
- Has been handed off to a backgrounded `pr-monitor` survey agent, which owns post-creation CI watching and fix-on-failure asynchronously.
