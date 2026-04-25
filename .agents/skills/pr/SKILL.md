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

### 1. Safety Checks & Branch Setup

First, verify the agent is on a safe branch and understand the current git state.

1. Run `git status` to see uncommitted/staged/untracked files.
2. Run `git branch --show-current` to identify the current branch.
3. **If on `develop` or `main` — STOP:**
   - Do NOT commit to these branches under any circumstances.
   - Analyze the uncommitted changes to understand what they're about.
   - Propose a branch name following repo conventions:
     - If changes relate to a spec: `[SPEC_NUMBER]-[short-name]` (e.g., `058-frontend-testing`)
     - Otherwise: `dga-[short-description]` (e.g., `dga-cleanup-graphql-queries`)
   - Present the proposed branch name to the user and wait for approval.
   - After approval, create the branch: `git checkout -b <branch-name>`.
4. If already on a feature branch, continue to the next phase.

### 2. Commit Changes (only when `commit` argument is provided)

**Skip this phase entirely if `commit` was NOT passed as an argument.** If there are uncommitted changes and `commit` was not provided, warn the user that uncommitted changes exist but will not be included in the PR.

When `commit` IS provided:

1. Run formatters and linters first (required by project conventions):

   ```bash
   uv run invoke format lint
   ```

2. Check if any GraphQL schema files were modified. If so, regenerate:

   ```bash
   uv run styrmin export graphql-schema schema.graphql
   uv run invoke generate
   ```

3. Stage all relevant changes (be specific — avoid `git add .` which can catch secrets or large files).
4. Create a commit with a clear conventional commit message (e.g., `feat:`, `fix:`, `refactor:`, `docs:`).
5. Push the branch upstream:

   ```bash
   git push -u origin <branch-name>
   ```

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

### 7. Monitor CI & Fix Issues

Don't just open the PR and walk away. Watch CI, especially linters — they frequently catch issues. Fix them proactively.

1. After PR creation, wait for the CI to start and monitor the actions runs (check every 30-60 seconds):

   ```bash
   gh run list --branch <branch-name> --limit 5
   ```

   The CI can take a few minutes to start. If nothing has started after 5 minutes, there might be an issue with the CI itself; investigate whether the PR introduced changes to the CI configuration.

2. Wait for at least all **linter jobs** to complete (check every 30-60 seconds).
3. If any jobs fail:
   - Read failure logs:

     ```bash
     gh run view <run-id> --log-failed
     ```

   - Reproduce the issue locally by running the same linter/check command.
   - Analyze the failure and propose a fix to the user.
   - After approval, commit the fix and push.
   - Continue monitoring until linters pass.
4. Report final CI status to the user.

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
- Has passing CI linters (with fixes pushed if needed).
