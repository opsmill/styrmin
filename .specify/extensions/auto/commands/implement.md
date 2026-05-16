---
description: Run the speckit implementation phase chunk-by-chunk in clean-context subagents, then review, then produce a final report. Picks up from an existing tasks.md.
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty). `$ARGUMENTS` is optional and may name the spec directory to operate on (e.g. `specs/008-foo`). If empty, operate on the most recently modified spec directory under `specs/` that has a `tasks.md`.

## Outline

You are running the **implementation + review tail** of the speckit pipeline. This command picks up where `speckit.auto.prep` leaves off: it expects a feature directory under `specs/` containing `spec.md`, `plan.md`, and `tasks.md`. It does **not** generate or modify those documents — it executes them.

The implementation phase runs as a **loop** over chunks of `tasks.md`, with each chunk implemented inside a **clean-context subagent**. The orchestrator (you) never edits feature code directly — it dispatches, integrates, and reports.

After all chunks are complete, you run a single review pass across the whole change set, fix any high-severity findings, and emit a final report.

> Each phase below is executed by invoking the named skill (e.g. via the agent's Skill tool). Skills are agent-agnostic, so this workflow runs identically across any harness that supports skill discovery — not only those exposing speckit slash commands.

### Phase 0 — Preflight

Before any work begins:

1. Resolve the target spec directory (from `$ARGUMENTS` or the most recently modified `specs/<feature>/` with a `tasks.md`). Record the absolute path; you will pass this to every subagent.
2. Verify `spec.md`, `plan.md`, and `tasks.md` all exist. If any are missing, abort with a clear error directing the user to run `speckit.auto.prep` first.
3. Read `tasks.md` end-to-end and identify the chunking boundaries (see "Chunking strategy" below). Build a numbered list of chunks with their task IDs.
4. Verify the working tree is clean (or only contains expected prep artifacts). If it is dirty in unrelated ways, surface that and pause.
5. Note the current `HEAD` commit — you will diff against it for the review and report.

### Phase 5 — Implement (looped, clean-context subagents)

Loop over the chunks identified in Phase 0. For **each chunk**:

1. **Dispatch a subagent with a clean context.** Use your harness's subagent / Task tool (in Claude Code: the `Agent` tool with `subagent_type=general-purpose`). The subagent **must not** inherit the orchestrator's conversation history — every chunk starts fresh.

2. **Brief the subagent self-contained.** The orchestrator has read context the subagent does not. The prompt to the subagent must include:
   - Absolute path to the spec directory.
   - Absolute path to the repository root.
   - A pointer to `AGENTS.md` / `CLAUDE.md` for project conventions (the subagent should read these first).
   - The **exact chunk** of tasks to implement, copied verbatim from `tasks.md` (task IDs, descriptions, and any `[P]` parallel markers).
   - An explicit instruction to invoke the `speckit-implement` skill scoped to **only those task IDs** — not the full `tasks.md`.
   - The commit policy: the subagent should run formatters/linters and commit its own work via the `speckit-checkpoint-commit` skill before returning.
   - **The E2E local-pass policy (Constitution §V).** Any E2E test the subagent adds or modifies MUST be observed to PASS locally at least once before the chunk is reported as done. Marker-clean / lint-clean / type-clean is NOT a substitute. For each such test the subagent MUST return the evidence specified in the response contract below; if it cannot produce the evidence, the chunk's outcome line for that task MUST be `⚠️ partial` or `❌ blocked` (not ✅ done) with the reason.
   - A short response contract: return (a) a one-line outcome per task ID (✅ done / ⚠️ partial / ❌ blocked + reason), (b) the commit SHA(s) it produced, (c) any decisions worth flagging upward, (d) test/lint status, (e) **for every new/modified E2E test: node ID, exact pytest command, ISO 8601 wall-clock timestamp of the passing run, cluster identifier (e.g. `vcluster<N>` + kubeconfig path), and the verbatim `PASSED ...` line from pytest output**. If the chunk added or modified no E2E tests, the subagent MUST say so explicitly so the orchestrator can record "n/a" rather than an omission.
   - Length cap on the report (e.g. "under 250 words", excluding the E2E evidence block which has no cap) so the orchestrator's context does not balloon.

3. **Wait for the subagent to return**, then:
   - Pull its outcome lines into your running ledger of chunk results.
   - Verify `tasks.md` checkboxes for that chunk are now `[X]` (re-read the file). If the subagent forgot to tick them, do it yourself and amend or add a fixup commit.
   - If the subagent reports ❌ blocked: do not auto-retry blindly. Decide between (i) re-dispatching with sharper instructions, (ii) splitting the chunk smaller and retrying, or (iii) recording the block and moving on. State which you chose and why.
   - Do **not** invoke `speckit-checkpoint-commit` again here — the subagent already committed. Only commit yourself if you applied a fixup (e.g. ticking missed checkboxes).

4. Move to the next chunk. **Never run two implementation subagents in parallel** — chunks may share files and conflicting writes are far more expensive than the wall-clock savings.

#### Chunking strategy

Prefer the natural phase headings already present in `tasks.md` (`### Phase 3.1: Setup`, `### Phase 3.2: Tests First (TDD)`, `### Phase 3.3: Core Implementation`, etc.). Each phase becomes one chunk.

If a phase contains more than ~10 tasks or touches > ~15 files, split it further along cohesive seams (e.g. one chunk per module, one chunk per contract test). If two adjacent small phases together total < ~5 tasks, do **not** merge them — keep the boundary; small chunks help review and reduce blast radius if a subagent goes off the rails.

Respect explicit dependencies in `tasks.md`. Sequential `[P]`-free tasks must stay in their original order across chunks; `[P]` markers within a chunk are fine for the subagent to parallelise internally.

### Phase 6 — Review

Once **all** chunks have completed (including any retries), invoke the `speckit-review-run` skill once across the full diff (`HEAD`-at-start..`HEAD`-now).

- For findings rated **high severity or above**, fix them inline. Prefer fixing them yourself if the change is small and localised; dispatch a fresh clean-context subagent (same protocol as Phase 5) if the fix spans multiple files or needs significant code understanding.
- For lower-severity findings, record them in the report (do not block).
- Commit any review-driven fixes via `speckit-checkpoint-commit`.

### Phase 7 — Final Report

Write a markdown report to `<spec-dir>/auto-implement-report.md` and also print it to the user. The report **must** contain:

1. **Header** — feature name, spec dir, base commit, head commit, total wall-clock time if known.
2. **Chunk-by-chunk ledger** — for each chunk dispatched, in order:
   - Chunk name (phase heading from `tasks.md`).
   - Number of tasks in the chunk.
   - Outcome counts (✅ / ⚠️ / ❌).
   - Commit SHA(s) produced by the subagent.
   - Any decisions or surprises the subagent flagged upward.
3. **Tasks not completed** — task IDs still `[ ]` in `tasks.md`, with the reason from the relevant subagent's report. Empty section if everything is `[X]`.
4. **E2E local-pass evidence (REQUIRED — Constitution §V).** A table of every E2E test added or modified by this run, with one row per test:

   | Node ID | Pytest command | Passed at (ISO 8601) | Cluster id | Verbatim PASSED line |
   |---------|----------------|----------------------|------------|----------------------|

   Aggregate the rows from each chunk subagent's response. If a chunk added/modified an E2E test but did not return evidence, the row's "Passed at" cell MUST be `MISSING — see chunk <N>` and the test MUST also appear in §3 "Tasks not completed" as a blocker — never silently elide it. If no E2E tests were added or modified by the whole run, write `n/a — no new or modified E2E tests in this implementation` instead of the table and state it explicitly so reviewers can verify the claim against the diff.
5. **Review findings** — table of severity / file / one-line summary. Mark which were fixed inline and which were deferred.
6. **Autonomous decisions** — any judgment calls the orchestrator made that the user might want to revisit (chunk splits, blocked-task handling, review-finding triage choices).
7. **Suggested next steps** — e.g. "open a PR", "rerun `speckit.auto.implement` to retry the 2 blocked tasks", "address the deferred review findings".

**Blocking rule.** If §4 contains any `MISSING` row, the report header MUST mark the run `INCOMPLETE` and §7 MUST list "produce local-pass evidence for the listed E2E tests" as the first next step. Do not declare the spec done while local-pass evidence is missing.

Commit the report via `speckit-checkpoint-commit` as the final action.

## Completion

Print a 4-6 line summary mirroring the report header + outcome counts so the user does not need to open the file to know the result. Then stop — do **not** open a PR, do **not** push, do **not** start a new feature. The user will take it from there.
