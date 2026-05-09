# Contract: Slash-Command Protocol for Bug Pipeline

This contract defines the surface that maintainers interact with — the slash commands typed in GitHub comments or invoked from the local CLI — and the matching rules that gate workflow triggers.

## Commands

| Command | Argument | Posted on | Triggers (CI) |
|---------|----------|-----------|----------------|
| `/bug-analyze <issue>` | issue number or URL | issue comment | `bug-agent-analyst.yml` |
| `/bug-fix <issue>` | issue number or URL | issue comment | `bug-agent-fix.yml` |
| `/bug-test <issue\|pr>` | issue/PR number or URL | issue comment **or** PR comment | `bug-agent-test.yml` |
| `/bug-review <pr>` | PR number or URL | PR comment | `bug-agent-review.yml` |

All four commands are also runnable from the local Claude Code CLI by typing the command directly (the skills are surfaced in the project's skill registry).

## Argument formats

Both forms are accepted by every stage and produce the same canonicalised pair `(number, url)`:

- **Bare integer**: `206` — the skill resolves it against the current repository (via `gh repo view --json url`).
- **Full URL**: `https://github.com/opsmill/styrmin/issues/206` (or `…/pull/206`) — the skill extracts the number from the path.

Empty or malformed arguments fail loudly with a usage message; the skill MUST NOT proceed with a guessed value.

## Trigger matching rules (workflow YAML)

Each workflow's `if:` clause matches against the **first line** of `github.event.comment.body`. Both with-argument and no-argument forms must trigger so the skill itself can post a usage comment for malformed invocations:

```yaml
if: |
  github.event_name == 'issue_comment' && (
    startsWith(github.event.comment.body, '/bug-analyze ') ||
    github.event.comment.body == '/bug-analyze' ||
    startsWith(github.event.comment.body, '/bug-analyze\n')
  )
```

(repeat the equivalent block for `/bug-fix`, `/bug-test`, `/bug-review`).

This rule deliberately:
- **Excludes** comments that quote the command (e.g., `> /bug-analyze 206`) — the leading `>` prevents the prefix match.
- **Excludes** comments that mention the command mid-paragraph — only line-start invocations fire.
- **Includes** invocations with no argument so the skill can respond with a usage message rather than the user seeing no feedback at all.

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

The skills must produce **identical observable side effects** whether invoked locally (`/bug-analyze 206` in Claude Code CLI) or from a workflow run (`/bug-analyze ${{ github.event.issue.number }}` in `bug-agent-analyst.yml`). Implementation difference is limited to the argument source — the skill body is identical.
