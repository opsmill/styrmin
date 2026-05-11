---
name: commit
description: Commit the latest changes to a safe feature branch — never to `main`, `stable`, or `develop`. Creates a new branch with a meaningful name when needed, and optionally pushes upstream.
argument-hint: Optional `push` to push the branch upstream after committing.
compatibility: Requires a Git working tree.
---

# Commit Changes

## Introduction

Stage and commit the current changes onto a safe feature branch. This skill enforces branch discipline — it will refuse to commit to `main`, `stable`, or `develop` and will create a new feature branch with a meaningful name when the current branch is protected. It works equally well for brand-new work and for additional commits on an existing feature branch. If the user passes `push`, the branch is pushed upstream after the commit.

## Arguments

<arguments> $ARGUMENTS </arguments>

**Supported arguments:**

- `push` — After committing, push the branch upstream (`git push -u origin <branch>` on first push, otherwise `git push`).

## Main Tasks

### 1. Assess Current State

1. Run `git status` to see staged, unstaged, and untracked files.
2. Run `git branch --show-current` to identify the current branch.
3. Run `git diff --stat` and `git diff --cached --stat` to summarise the change footprint.
4. If there are no changes to commit (working tree clean, nothing staged) — STOP and tell the user there's nothing to commit. Do not create an empty commit.

### 2. Branch Safety — Never Commit to Protected Branches

The protected branches are: `main`, `stable`, `develop`.

- **If the current branch is one of those:**
  1. Do NOT commit on the current branch.
  2. Analyse the changes (diffs from step 1) to understand their nature.
  3. Propose a branch name following repo conventions:
     - If the changes clearly relate to a spec under `specs/` (e.g., `specs/058-frontend-testing/`), use `[SPEC_NUMBER]-[short-name]` (e.g., `058-frontend-testing`).
     - Otherwise, use `dga-[short-description]` with a concise kebab-case description of the work (e.g., `dga-fix-graphql-codegen`, `dga-add-commit-skill`).
  4. Present the proposed branch name to the user and wait for explicit approval (the user may suggest a different name).
  5. After approval, create and switch to the branch: `git checkout -b <branch-name>`. The uncommitted changes carry across automatically.

- **If the current branch is already a feature branch:** continue on it. Do not create a new branch unless the user explicitly asks for one.

### 3. Stage Changes

1. Review what will be staged. Prefer adding files explicitly by path rather than `git add -A` or `git add .`, especially when untracked files are present — this avoids accidentally committing secrets (`.env`, credentials, key files) or large/generated artefacts.
2. If staged changes already exist (the user pre-staged), respect that staging and only add additional files when it's clearly intended.
3. Warn the user and require explicit confirmation before staging any file that looks sensitive (`.env*`, `*secret*`, `*credential*`, `*.key`, `*.pem`) or generated/large (`node_modules/`, build artefacts, `dist/`, `__pycache__/`, lockfiles changed unexpectedly).

### 4. Draft the Commit Message

Follow the repo's conventional-commit style (visible in `git log`):

- Use a type prefix: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`, `chore:`, `ci:`, etc.
- Optional scope in parentheses: `feat(backend): ...`, `fix(e2e): ...`.
- Subject line under ~72 characters, imperative mood, no trailing period.
- Focus on the *why* — what changed in terms of behaviour or capability, not a file list.
- For multi-area changes, add a short body explaining the motivation.

Examples (drawn from this repo's recent history):

- `fix(e2e): correct timeline access in env-update fanout test`
- `docs(extract): archive specs 008-011 + extract durable knowledge`
- `feat: add commit skill for safe branch discipline`

Present the proposed commit message to the user before committing. Adjust based on feedback.

### 5. Create the Commit

1. Run `git commit -m "<message>"`. For multi-line messages, use a HEREDOC:

   ```bash
   git commit -m "$(cat <<'EOF'
   <subject>

   <body>
   EOF
   )"
   ```

2. Do NOT pass `--no-verify` — let pre-commit hooks run. If a hook fails:
   - Read the hook output carefully.
   - Fix the underlying issue (formatting, lint, etc.) rather than bypassing.
   - Re-stage the fixed files and create a NEW commit. Do not `--amend` after a failed hook run, because the previous commit context may already be on the branch.
3. Run `git status` after the commit to confirm a clean tree and verify success.
4. Run `git log -1 --stat` so the user can see what landed.

### 6. Push Upstream (only when `push` argument is provided)

**Skip this phase entirely if `push` was NOT passed.**

When `push` IS provided:

1. Re-verify the branch is not `main`, `stable`, or `develop` (defence in depth — though step 2 should have prevented this).
2. Check whether the branch already tracks a remote:
   - `git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null`
3. If no upstream exists: `git push -u origin <branch-name>`.
4. If an upstream exists: `git push`.
5. **Never use `--force` or `--force-with-lease`** unless the user explicitly asks for it. Regular `git push` will fail if the remote has diverged — surface that error to the user instead of overwriting.
6. Report the push result and, if a remote URL is configured (`git config --get remote.origin.url`), the branch URL the user can open.

## Notes

**Branch Safety:**

- This skill will NEVER commit to `main`, `stable`, or `develop`.
- If asked to override that rule, refuse and explain — the user can switch branches themselves first if they truly intend to commit there (in which case this skill no longer applies).

**Secret Hygiene:**

- Prefer explicit `git add <path>` over wholesale `git add -A`.
- Warn before staging anything that looks like a secret or credential.

**Hook Discipline:**

- Pre-commit hooks exist for good reasons (see `dev/guides/pre-commit-hooks.md`). Fix violations rather than bypassing.

**Idempotency:**

- Safe to invoke repeatedly. With no changes to commit, the skill exits cleanly without creating an empty commit.

## Expected Outcome

- All staged/unstaged changes that the user wanted to capture are committed on a safe feature branch.
- The branch is named meaningfully (existing name preserved, or new `NNN-...` / `dga-...` name approved by the user).
- The commit message follows conventional-commit style.
- If `push` was provided, the branch is pushed upstream.
- `main`, `stable`, and `develop` are untouched in all cases.
