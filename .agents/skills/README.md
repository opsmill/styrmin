# Agent Skills

This directory holds **agent-agnostic skills** — reusable workflow definitions that any agent runtime can consume. A skill packages an operational workflow (intent, prerequisites, step-by-step guidance, expected outcome) in a portable format so it can be loaded by Claude Code, OpenAI Codex, Cursor, custom agents, or any other tool that knows how to read the convention below.

## Layout

Each skill is a self-contained directory with a single `SKILL.md` file at its root:

```
.agents/skills/
├── README.md                           # This document
├── <skill-name>/
│   └── SKILL.md                        # Required entry point
└── <other-skill>/
    ├── SKILL.md
    └── <supporting-files>              # Optional: scripts, templates, examples
```

Conventions:

- **Directory name = skill name**, in `kebab-case`. The directory name is the canonical identifier an agent uses to invoke the skill.
- **`SKILL.md` is required.** It is the only file every agent runtime is guaranteed to read. Supporting files (scripts, templates, additional reference docs) may live alongside it and be referenced from `SKILL.md` by relative path.
- **Skills are self-contained.** A skill should not require files outside its own directory other than well-known repository paths (e.g., `dev/`, `backend/`, `.specify/`).

## `SKILL.md` Format

Every `SKILL.md` starts with a YAML front-matter block followed by Markdown body content.

### Front-matter

```yaml
---
name: <kebab-case identifier — must match the directory name>
description: <one-sentence summary used for skill discovery and selection>
argument-hint: <optional: short hint describing the expected argument string>
compatibility: <optional: prerequisites such as required tools or repo layout>
metadata:
  source: <optional: original location, e.g. .agents/commands/foo.md>
  author: <optional>
---
```

Field semantics:

| Field | Required | Purpose |
|-------|----------|---------|
| `name` | Yes | Stable identifier. Agents address the skill by this name. |
| `description` | Yes | Short, action-oriented summary. Agents use this to decide whether the skill is relevant to a request. |
| `argument-hint` | No | Hint about what string (if any) the user is expected to pass when invoking the skill. |
| `compatibility` | No | Prerequisites — required CLI tools, repo structure, or framework state. |
| `metadata` | No | Free-form provenance metadata. Agents may ignore it. |

Agent-specific keys (for example `user-invocable`, `disable-model-invocation`) are permitted but optional. Runtimes that do not understand a key MUST ignore it rather than fail.

### Body

The Markdown body describes the workflow itself. Recommended structure:

1. **Title** — H1 heading naming the skill in human-readable form.
2. **Introduction / purpose** — what the skill does and when to use it.
3. **Arguments** — if the skill accepts arguments, document them (refer to them via the `$ARGUMENTS` placeholder, which agents substitute at invocation time).
4. **Prerequisites** — tools, permissions, or repo state the skill assumes.
5. **Steps / Phases** — the actual operational guidance, in order.
6. **Notes** — guard-rails, safety considerations, edge cases.
7. **Expected outcome** — observable result when the skill completes successfully.

Skills SHOULD NOT embed agent-specific syntax in the body (no Claude Code slash-command notation, no Cursor-specific prompt blocks). Where a tool is referenced (e.g., `gh`, `kubectl`, `git`), prefer the underlying CLI rather than a tool-specific wrapper, so any agent capable of running shell commands can execute the workflow.

## Discovery

Agents discover the available skills by scanning this directory:

1. List immediate subdirectories of `.agents/skills/`.
2. For each subdirectory, read `SKILL.md` and parse the YAML front-matter.
3. Index the skill by `name` and surface `description` (and optionally `argument-hint`) in the agent's skill picker.

Equivalent shell discovery (useful for CI checks or tooling):

```bash
find .agents/skills -mindepth 2 -maxdepth 2 -name SKILL.md
```

## Invocation

How a skill is triggered depends on the runtime:

- **Claude Code**: typed as `/<skill-name>` or selected via the Skill tool.
- **Custom agents using the Claude Agent SDK**: loaded as a tool definition or system-prompt fragment.
- **Other runtimes**: consult that runtime's skill loader. The contract is the same — the skill body becomes operational guidance the agent follows verbatim.

When a runtime substitutes argument text, it replaces the literal string `$ARGUMENTS` in the body with whatever the user supplied at invocation time.

## Adding a New Skill

1. Create `.agents/skills/<skill-name>/SKILL.md`.
2. Fill in the front-matter (`name`, `description`, plus any optional fields).
3. Write the body following the recommended structure above.
4. Verify discovery:

   ```bash
   find .agents/skills -mindepth 2 -maxdepth 2 -name SKILL.md
   ```

5. If the skill is also useful as a command in a runtime that scans `.agents/commands/`, you MAY add a thin pointer document there — but `SKILL.md` is the canonical source.

## Relationship to `.agents/commands/`

The legacy `.agents/commands/` directory holds command-style prompt documents historically consumed by a single agent runtime. Core repo workflows have been migrated into this directory as portable skills. Spec Kit installs its own skills here (`speckit-*`), from its own installation and distribution model; do not edit them by hand, because the next Spec Kit upgrade regenerates them.
