# Spec/Ask Alignment Check: Environment Clone

**Feature**: 010-environment-clone | **Date**: 2026-08-19

## Source

- **PRD**: https://github.com/opsmill/styrmin/issues/6#issuecomment-5208479529 — the
  "Idea Brief: Environment Clone" produced by a `/grilling-ideas` session (fetched via
  `gh api` at session start; used verbatim as the source of truth). The parent issue
  #6 body was also read for context; where the brief deliberately supersedes it
  (single-cluster only, network isolation split out), the brief governs — those
  exclusions are the brief's own explicit decisions.

## Verdict

**⚠️ MINOR DRIFT (proceeding)**

Every PRD requirement, journey, edge case, success criterion, assumption, and
out-of-scope item is present in `spec.md` — nothing is missing, dropped, or softened.
Three deliberate semantic refinements were made during planning/critique, each
preserving the PRD's stated intent and each traceable to a documented engineering
finding. None rises to significant drift (no requirement lost, no scope added beyond
the PRD's own motives, no PRD constraint contradicted).

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
|---|---|---|---|---|
| Minor | changed | FR-008 "refuse to delete an environment backup an in-flight clone depends on" | FR-008 | Narrowed to the **capture window**; post-capture deletion is allowed and becomes the documented escape hatch (drives a stuck clone to attributed FAILED). The PRD-literal reading creates a permanently-wedged state (clone flow dies post-capture → backup un-deletable forever), contradicting the escape-hatch philosophy the PRD itself builds on (ADR-055 decision 6). Intent — deletion must never silently strand a clone — is preserved via attribution. (Critique finding E2.) |
| Minor | changed | Edge case 4 "Concurrent clones of one source → allowed; independent backups, no lock" | Edge case "Concurrent clones of one source" | Concurrency preserved except during the **capture window**, which serialises with other environment-level operations on the source (typed busy error). Literal concurrent captures would trip the platform's per-instance backup guards and degrade both clones to PARTIAL; the PRD's intent (independent artefacts, no whole-clone lock) is preserved post-capture. (Research D8.) |
| Minor | added | FR-006 (override "merged over the copied config") + the brief's non-interference motive | FR-006, US3 scenario 3 | Added the ability to **clear** a copied config field, because the platform's override input cannot express "unset" for scalar fields — without it, production-only settings (e.g. external DNS integration) could only be replaced, never removed, defeating the PRD's own stated motive. Capability addition in direct service of a PRD goal, not new scope. (Critique finding P2.) |
| Info | added | — (gap) | Edge cases: partially successful capture; mutating the under-construction environment; deleting the source mid-clone; backing-backup deletion timing | New edge cases decide states the PRD did not consider; each resolves an internal contradiction or race found in critique (E5, E6, E8). Necessary clarifications, consistent with the PRD's PARTIAL philosophy. |
| Info | added | Isolation motive discussion ("clone of production … may actively interfere") | Assumptions: "Scope of the non-interference mitigation" | Honest scoping statement: the override mitigates configuration-level interference only; data-borne credentials are cloned verbatim. Makes a PRD-implied limitation explicit rather than changing scope. (Critique X1.) |
| Info | expanded | FR-011/FR-012 absent as numbered FRs in the PRD | FR-011, FR-012 | Promoted verbatim from PRD edge case 1 (name-taken) and PRD SC-001 (four-surface parity) into numbered requirements — traceable restatements, not additions. |

Verified item-by-item: PRD FR-001–FR-010 all present (FR-001, 003, 004, 005, 007,
009, 010 essentially verbatim); PRD FR-002's "unless that backup succeeds" refined to
"restorable terminal status (COMPLETED or PARTIAL)" — the PRD left the PARTIAL-capture
case undecided while its own edge case 2 embraces PARTIAL progression, so this is a
gap-fill, not a change of meaning. All five PRD success criteria preserved
(SC-001–SC-005 near-verbatim). All seven PRD out-of-scope items preserved. All PRD
assumptions preserved. Key entities match, including the PRD's named
"cross-target constituent restore" mechanism demand.

## Action

**Proceed.** No remediation pass required (0 of 2 budget used). The three minor
refinements are documented here, in the spec text itself (edge case 4 carries its
"refinement from planning" note), in `research.md` (D7, D8, D9), and in the critique
report — the PR reviewer sees the full trail.
