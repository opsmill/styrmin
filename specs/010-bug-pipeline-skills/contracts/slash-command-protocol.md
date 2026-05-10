# Contract: Slash-Command Protocol for Bug Pipeline

This contract defines the surface that maintainers interact with — the slash commands typed in GitHub comments or invoked from the local CLI — and the matching rules that gate workflow triggers.

## Commands

| Command | Argument | Posted on | Triggers (CI source / lock file) |
|---------|----------|-----------|----------------|
| `/bug-analyze <issue>` | issue number or URL | issue comment | `bug-agent-analyst.md` → `bug-agent-analyst.lock.yml` |
| `/bug-fix <issue>` | issue number or URL | issue comment | `bug-agent-fix.md` → `bug-agent-fix.lock.yml` |
| `/bug-test <issue\|pr>` | issue/PR number or URL | issue comment **or** PR comment | `bug-agent-test.md` → `bug-agent-test.lock.yml` |
| `/bug-review <pr>` | PR number or URL | PR comment | `bug-agent-review.md` → `bug-agent-review.lock.yml` |

All four commands are also runnable from the local Claude Code CLI by typing the command directly (the skills are surfaced in the project's skill registry).

## Argument formats

Both forms are accepted by every stage and produce the same canonicalised pair `(number, url)`:

- **Bare integer**: `206` — the skill resolves it against the current repository (via `gh repo view --json url`).
- **Full URL**: `https://github.com/opsmill/styrmin/issues/206` (or `…/pull/206`) — the skill extracts the number from the path.

Empty or malformed arguments fail loudly with a usage message; the skill MUST NOT proceed with a guessed value.

## Trigger matching rules (GHAW source)

As of Iteration 2026-05-09 (HYBRID GHAW adoption), the trigger is declared in the GHAW `.md` source frontmatter using the `slash_command:` primitive. The GHAW compiler emits the line-anchored matching logic into the generated `.lock.yml`; behaviour from the maintainer's perspective is unchanged.

Frontmatter shape (per `.md` source):

```yaml
---
description: <one-line description of the stage>
on:
  slash_command:
    name: bug-<stage>
    events: [issue_comment]
engine: claude
permissions:
  contents: write
  pull-requests: write
  issues: write
  id-token: write
  actions: read
concurrency:
  group: bug-pipeline-${{ github.event.issue.number }}
  cancel-in-progress: false
---

/bug-<stage> ${{ github.event.issue.number }}
```

The body of the `.md` is exactly the slash-command invocation — one line — and contains no agent prompt, no branch logic, and no comment formatting (per FR-024). All agent logic is in the corresponding `.agents/skills/bug-<stage>/SKILL.md`.

This trigger model deliberately:

- **Matches only line-start invocations** of the slash command — embedded mentions in long discussion comments don't fire it.
- **Includes invocations with no argument** so the skill can respond with a usage message rather than the user seeing no feedback at all.
- **Excludes quoted variants** (e.g., `> /bug-analyze 206` in a blockquote) — the leading `>` prevents the prefix match.

The exact regex GHAW emits into the `.lock.yml` is opaque to this contract; the contract specifies behaviour, not implementation.

### Skill responsibilities for invalid arguments

When triggered with no argument, an empty argument, or an argument that does not parse as a positive integer or canonical GitHub URL, the skill MUST:

1. Post a comment on the same issue/PR explaining the expected argument format and giving an example.
2. Stop without performing any other side effects (no branch, no PR, no further comments).

## Permission requirements

Workflow `permissions:` block (mirrors `claude.yml`):

```yaml
permissions:
  contents: write
  pull-requests: write
  issues: write
  id-token: write
  actions: read
```

GitHub's repository-level role gating (write or maintain) is what restricts who can trigger the workflows; the workflows themselves do not perform a custom membership check in v1.

## Output-comment conventions

Every stage's output comment ends with one of:

- **Success**: a final line containing the next-stage suggestion, e.g. `> Next: \`/bug-fix 206\``. The next-command suggestion is absent for the final stage (`bug-review`).
- **Failure**: no next-command line. Instead, a final paragraph summarising what was attempted and why the stage stopped.

The bug-pipeline never edits or deletes prior comments — every stage append a new comment.

## Local CLI vs CI parity

The skills must produce **identical observable side effects** whether invoked locally (`/bug-analyze 206` in Claude Code CLI) or from a workflow run (`/bug-analyze ${{ github.event.issue.number }}` in `bug-agent-analyst.md` / its compiled `.lock.yml`). Implementation difference is limited to the argument source — the skill body is identical, and HYBRID GHAW adoption keeps the workflow `.md` body to a single slash-command line so no logic forks between local and CI paths.
