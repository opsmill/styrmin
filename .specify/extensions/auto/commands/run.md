---
description: Run the full speckit workflow end-to-end — specify, plan, tasks, implement, review, extract — making all decisions autonomously.
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Outline

You are running the **full speckit pipeline** end-to-end. The user's input (above) is the feature description that will seed the specification phase.

Execute every phase below **in order**, making all decisions autonomously. Do not stop to ask the user for input between phases — if a phase requires choices (e.g., clarification questions in specify, research decisions in plan), use your best judgment and proceed. The user expects a hands-off, one-shot execution.

After **each phase**, invoke `/speckit.checkpoint.commit` to commit the artifacts produced by that phase before moving on.

### Phase 1 — Specify

Invoke `/speckit.specify` with the user's feature description (`$ARGUMENTS`).

- Complete the full specify workflow: generate a short name, create the spec directory, write `spec.md`, run quality checks.
- If clarification questions arise, answer them yourself based on context and best judgment — do **not** pause for user input.
- Commit the spec artifacts.

### Phase 2 — Plan

Invoke `/speckit.plan`.

- Complete the full plan workflow: research unknowns, generate `plan.md`, `research.md`, `data-model.md`, API contracts, `quickstart.md`.
- Make all design decisions autonomously.
- Commit the plan artifacts.

### Phase 3 — Tasks

Invoke `/speckit.tasks`.

- Generate the full `tasks.md` with dependency-ordered, actionable tasks.
- Skip the optional analysis (`speckit.analyze`) unless something looks inconsistent — use your judgment.
- Commit the tasks artifact.

### Phase 4 — Implement

Invoke `/speckit.implement`.

- Execute all tasks from `tasks.md` phase by phase.
- Commit at natural implementation checkpoints (after each task or logical group of tasks).
- Run formatters and linters as required by the project.
- If tests fail, fix them before moving on.

### Phase 5 — Review

Invoke `/speckit.review`.

- Run the comprehensive review across all enabled agents.
- For any findings rated **high severity or above**, fix them immediately and commit the fixes.
- For lower-severity findings, note them but do not block progress.

### Phase 6 — Extract

Invoke `/speckit.extract.run`.

- Extract ADRs, knowledge, and guidelines from the completed spec into `dev/`.
- Commit the extracted documentation.

## Completion

After all phases are complete, provide a brief summary:
- Feature name and spec directory
- Number of tasks completed
- Any review findings that were fixed
- Any notable decisions you made autonomously
