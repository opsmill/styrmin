---
name: speckit-auto-prep
description: Run the speckit preparation phases end-to-end — specify, plan, critique,
  tasks — making all decisions autonomously. Stops before implementation.
compatibility: Requires spec-kit project structure with .specify/ directory
metadata:
  author: github-spec-kit
  source: auto:commands/prep.md
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Outline

You are running the **preparation phases of the speckit pipeline** end-to-end. The user's input (above) is the feature description that will seed the specification phase.

This command is the prefix of `speckit.auto.run`: it covers Specify → Plan → Critique → Tasks and **stops before implementation**. Use it when you want a feature fully designed and broken down into a `tasks.md` ready for review, but you do not want the agent to execute the tasks autonomously.

Execute every phase below **in order**, making all decisions autonomously. Do not stop to ask the user for input between phases — if a phase requires choices (e.g., clarification questions in specify, research decisions in plan), use your best judgment and proceed. The user expects a hands-off, one-shot execution up through `tasks.md`.

After **each phase**, invoke the `speckit-checkpoint-commit` skill to commit the artifacts produced by that phase before moving on.

> Each phase below is executed by invoking the named skill (e.g. via the agent's Skill tool). Skills are agent-agnostic, so this workflow runs identically across any harness that supports skill discovery — not only those exposing speckit slash commands.

### Phase 1 — Specify

Invoke the `speckit-specify` skill with the user's feature description (`$ARGUMENTS`).

- Complete the full specify workflow: generate a short name, create the spec directory, write `spec.md`, run quality checks.
- If clarification questions arise, answer them yourself based on context and best judgment — do **not** pause for user input.
- Commit the spec artifacts.

### Phase 2 — Plan

Invoke the `speckit-plan` skill.

- Complete the full plan workflow: research unknowns, generate `plan.md`, `research.md`, `data-model.md`, API contracts, `quickstart.md`.
- Make all design decisions autonomously.
- Commit the plan artifacts.

### Phase 3 — Critique

Invoke the `speckit-critique-run` skill.

- Run the dual-lens (Product + Engineering) critique against `spec.md` and `plan.md` before any tasks are generated.
- For any 🎯 **Must-Address** findings, apply the suggested fixes to `spec.md` / `plan.md` autonomously and commit them — do not pause for user approval.
- For 💡 Recommendations, apply them when the fix is clear and low-risk; otherwise note and move on.
- 🤔 Questions: resolve with your best judgment based on context (same rule as the Specify phase).
- If the verdict is 🛑 **RETHINK**, loop back to `speckit-plan` (or `speckit-specify` if the spec itself is the problem), re-run the critique, then continue.
- Commit the critique report and any spec/plan updates before moving on.

### Phase 4 — Tasks

Invoke the `speckit-tasks` skill.

- Generate the full `tasks.md` with dependency-ordered, actionable tasks.
- Skip the optional `speckit-analyze` skill unless something looks inconsistent — use your judgment.
- Commit the tasks artifact.

## Completion

After all four phases are complete, provide a brief summary:
- Feature name and spec directory
- Number of tasks generated in `tasks.md`
- Any critique findings that were addressed inline
- Any notable decisions you made autonomously

Do **not** proceed to implementation, review, or extraction. The user will run those phases (or `speckit.auto.run` from scratch) when ready.