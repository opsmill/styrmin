---
name: rebase
description: Rebase the current branch onto the latest base branch, resolving conflicts while preserving the intent of local changes; optionally force-push and monitor CI.
argument-hint: Optional `push` to force-push and monitor CI after a successful rebase
compatibility: Requires a Git working tree. CI monitoring requires GitHub access (gh CLI authenticated, GitHub MCP server, or equivalent).
metadata:
  source: .agents/commands/rebase.md
---

# Rebase Branch

## Introduction

Rebase the current branch onto the latest base branch, resolving any merge conflicts by preserving the intent of local changes. Optionally force-push and monitor CI status on GitHub.

## Arguments

<arguments> $ARGUMENTS </arguments>

**Supported arguments:**

- `push` — After a successful rebase, force-push the branch upstream and monitor GitHub Actions CI until completion.

## Main Tasks

### 1. Assess Current State

Understand the branch topology and working tree before doing anything destructive.

1. Run `git status` to check for uncommitted changes.
2. Run `git branch --show-current` to identify the current branch.
3. **If on `develop` or `main` — STOP:** Rebasing these branches is not allowed. Inform the user and exit.
4. **If there are uncommitted changes — STOP:** Inform the user they must commit or stash changes before rebasing. Do not proceed.
5. Identify the base branch:
   - Default: `develop`.
   - If the branch was clearly forked from another branch, use that instead.
6. Show the user a summary:
   - Current branch name.
   - Base branch.
   - Number of local commits (`git log develop..HEAD --oneline`).

### 2. Update Base Branch & Rebase

1. Fetch the latest remote state:

   ```bash
   git fetch origin
   ```

2. Start the rebase:

   ```bash
   git rebase origin/<base-branch>
   ```

3. If the rebase completes cleanly, skip to Phase 4.

### 3. Resolve Merge Conflicts

When conflicts arise, understand what the local commits intended to do and preserve that intent while incorporating upstream changes. For each conflict, read both sides and make an informed resolution.

For each conflict that arises during the rebase:

1. Identify conflicting files:

   ```bash
   git diff --name-only --diff-filter=U
   ```

2. For each conflicting file:
   - Read the file to see the conflict markers.
   - Read the local commit that introduced the change (`git log --oneline -1`).
   - Understand what the upstream change did vs what the local change intended.
   - Resolve the conflict by **preserving the intent of local changes** while incorporating any non-conflicting upstream changes.
   - Stage the resolved file:

     ```bash
     git add <file>
     ```

3. Continue the rebase:

   ```bash
   git rebase --continue
   ```

4. Repeat until the rebase completes. If a conflict is ambiguous, present both sides to the user and ask how to resolve it.
5. After all conflicts are resolved, show the user a summary of what was resolved.

### 4. Verify Rebase Result

1. Run a quick sanity check:

   ```bash
   git log develop..HEAD --oneline
   ```

2. Confirm the commit history looks correct (same number of local commits, no duplicates).
3. If the project has fast validation commands, consider running formatters to catch any resolution issues:

   ```bash
   uv run invoke format lint
   ```

   Fix any issues introduced by conflict resolution.

### 5. Force Push & Monitor CI (only when `push` argument is provided)

**Skip this phase entirely if `push` was NOT passed as an argument.** Instead, inform the user the rebase is complete and they can push when ready.

When `push` IS provided:

1. Force-push the rebased branch:

   ```bash
   git push --force-with-lease origin <branch-name>
   ```

   Use `--force-with-lease` as a safety measure to avoid overwriting unexpected upstream changes.

2. Monitor GitHub Actions CI (be patient — CI can take several minutes to start):

   ```bash
   gh run list --branch <branch-name> --limit 5
   ```

   - Check every 30-60 seconds.
   - If nothing has started after 5 minutes, investigate whether the push triggered a workflow.

3. Wait for CI jobs to complete (check every 30-60 seconds):

   ```bash
   gh run list --branch <branch-name> --limit 5
   ```

4. If any jobs fail:
   - Read failure logs:

     ```bash
     gh run view <run-id> --log-failed
     ```

   - Analyze the failure and propose a fix to the user.
   - After approval, commit the fix, push, and continue monitoring.

5. Report final CI status to the user.

## Notes

**Branch Safety:**

- This skill will NEVER rebase `develop` or `main`.
- Uses `--force-with-lease` instead of `--force` to prevent overwriting unexpected remote changes.
- Will not proceed with uncommitted changes in the working tree.

**Conflict Resolution Strategy:**

- Local changes take priority — the goal is to land *our* work on top of the latest base.
- When both sides modify the same logic in incompatible ways, ask the user.
- After resolution, run formatters/linters to catch any issues introduced by the merge.

## Expected Outcome

A branch that:

- Is cleanly rebased onto the latest base branch.
- Has all merge conflicts resolved preserving local intent.
- Passes formatters and linters after resolution.
- (When `push` is provided) Is force-pushed upstream with passing CI.
