# spec-kit-auto

A [spec-kit](https://github.com/github/spec-kit) extension that runs the speckit workflow end-to-end with autonomous decision-making — specify, plan, critique, tasks, implement, review, extract — so you can throw a feature description at the agent and walk away.

## What Problem Does This Solve?

The standard speckit workflow is a sequence of agent commands that each pause for user review. That's the right default for high-stakes work, but it's overkill when you want to hand off a well-scoped feature and come back to a finished result. `spec-kit-auto` runs the pipeline back-to-back, committing after each phase, so the agent doesn't need babysitting.

It also splits the pipeline at its natural seam — preparation vs. implementation — so you can run only the half you want autonomous and review the other half manually.

## Commands

The extension provides three commands. `auto.run` is a thin orchestrator over the other two — there is exactly one source of truth for each phase.

- **`/speckit.auto.prep`** — Preparation phases. Specify → Plan → Critique → Tasks → **Spec/Ask Alignment Check**. Stops with a reviewable `tasks.md` and an `alignment-check.md` confirming the spec still matches the user's original ask (especially when the ask is a detailed PRD or a link to one).
- **`/speckit.auto.implement`** — Implementation tail. Picks up an existing `tasks.md` and runs Implement → Review → Final report, executing each chunk inside a clean-context subagent so the orchestrator's context stays small. Use after `/speckit.auto.prep` (or after manual prep) when you're ready to let the agent execute.
- **`/speckit.auto.run`** — Full pipeline. Invokes `auto.prep`, then `auto.implement`, then a final extraction pass — no duplicated phase logic. Use when you trust the agent to take a feature description all the way to merged code without you in the loop.

After each phase, the agent invokes `/speckit.checkpoint.commit` to commit the artifacts produced. Clarifications and design decisions are made autonomously — the workflow does not pause for user input between phases.

### Spec/Ask Alignment Check

`auto.prep`'s last phase compares the generated `spec.md` against the user's original ask, with two important behaviours:

- **URL-aware** — if `$ARGUMENTS` contains a link to a PRD (Notion, Confluence, Google Doc, GitHub issue, Linear ticket, etc.), the check fetches the link and uses its body as the source-of-truth PRD. PRDs are commonly delivered as links, not pasted inline.
- **Auto-remediation with a retry budget** — if the spec has significantly drifted (missing requirements, added scope, changed semantics, dropped acceptance criteria, contradicted constraints), the check updates `spec.md` and re-runs Plan → Critique → Tasks, then re-validates. Up to 2 remediation passes; if drift persists, it stops and surfaces an `🛑 UNRESOLVED — manual review required` verdict rather than silently proceeding.

The check is skipped automatically when the ask is a one-liner or empty (no PRD to compare against).

## Quick Start

### Prerequisites

- [spec-kit](https://github.com/github/spec-kit) >= 0.1.0
- The following speckit commands available in your environment:
  - `speckit.specify`, `speckit.plan`, `speckit.tasks`, `speckit.implement`
  - `speckit.critique.run`
  - `speckit.review` (from the `review` extension)
  - `speckit.extract.run` (from the `extract` extension)
  - `speckit.checkpoint.commit` (from the `checkpoint` extension)

### Installation

```bash
specify extension add /path/to/spec-kit-auto --dev
```

## Usage

```
/speckit.auto.run <feature description>
/speckit.auto.prep <feature description>
/speckit.auto.implement [spec-dir]
```

`/speckit.auto.implement` takes an optional spec directory argument (e.g. `specs/008-foo`); if omitted it operates on the most recently modified `specs/<feature>/` that has a `tasks.md`.

When finished, each command reports a summary:

- Feature name and spec directory
- Number of tasks generated and/or completed
- Any critique or review findings that were fixed inline
- Alignment check status — verdict, source PRD reference, and how many remediation passes were used (only from `auto.prep` and `auto.run`)
- Any notable decisions made autonomously

## When to Use This

Reach for these commands when the feature is well-scoped enough that you trust the agent to make reasonable judgment calls without you in the loop. For high-stakes or ambiguous work, prefer running the phases individually so you can review between steps.

A common middle-ground workflow: run `/speckit.auto.prep`, review and tweak `tasks.md`, then run `/speckit.auto.implement` to execute it.

## Project Structure

```
extension.yml          # Extension metadata and command registration
commands/
  prep.md              # Preparation (specify → ... → tasks → alignment check)
  implement.md         # Implementation tail (implement → review → report)
  run.md               # Orchestrator: invokes prep + implement + extract
```

## License

[MIT](LICENSE)
