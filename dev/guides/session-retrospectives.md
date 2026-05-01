# Session Retrospectives

Use `speckit.retrospect` at the end of an agent session when the session exposed avoidable context-management friction. The command is provided by the SpecKit `retrospect` extension under `.specify/extensions/retrospect/`; it reviews the current conversation and proposes improvements to shared instructions, skills, templates, documentation, and architecture follow-up.

## When to Run

Run a retrospective when one or more of these happened:

- The agent needed inline correction for a repository convention that should have been documented.
- A skill prompt or spec-kit template missed a step that proved necessary.
- A guide, knowledge page, or ADR contradicted the current code.
- A product or architecture choice caused repeated workarounds worth tracking.
- The agent took a wrong path that a reusable guardrail could prevent.

## Command Source

The extension source lives at:

```text
.specify/extensions/retrospect/
```

The runtime command is registered as:

```text
.agents/commands/speckit.retrospect.run.md
.agents/commands/speckit.retrospect.md
```

Update the extension command source first, then refresh the runtime command using the same extension-managed pattern as the other `speckit.*` commands.

## What It Produces

The report is organized into four categories:

- **Instructions / Configuration Gaps**: Missing or unclear guidance in `AGENTS.md`, `CLAUDE.md`, `.claude/settings.json`, skill prompts, commands, or templates.
- **Documentation Gaps**: Missing or stale content in `dev/knowledge/`, `dev/guides/`, `dev/guidelines/`, or `dev/adr/`.
- **Architectural Friction**: Product or code choices that caused repeated workarounds and may need ADRs, refactors, or issues.
- **Mistakes & Corrections**: Wrong turns from the session and the guardrail that would have prevented them.

Each finding gets a disposition:

- `fix-now`: apply a small, low-risk repo context update on the current branch after approval and diff preview.
- `open-pr`: prepare a dedicated PR plan for changes that should not ride along with the current feature.
- `github-issue`: draft a GitHub issue through the existing `create-issue` workflow.
- `local-only`: record a personal or project-local note that should not become repo policy.

## Safety Rules

The skill is read-only until the user approves saving the report or acting on a disposition bucket. It must not silently edit files, create issues, commit, push, or open PRs.

Ask First topics from `AGENTS.md`, including database migrations, GraphQL schema changes, new dependencies, CI/CD workflow changes, authentication, and authorization, are never assigned to `fix-now`. Generated files are never edited.

## Report Location

When run inside a spec-kit feature, the report is saved to:

```text
specs/<current-feature>/retrospective.md
```

For ad-hoc sessions, the report is saved to:

```text
.claude/retrospectives/YYYYMMDD-HHMMSS-<short-branch-or-session-slug>.md
```

If a report already exists at the target path, use a numeric suffix rather than overwriting it.
