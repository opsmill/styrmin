---
name: create-prd
description: Synthesize the current conversation into a Styrmin-flavoured PRD and publish it to GitHub — as a comment on the issue referenced at the start of the conversation, or as a new issue if none was referenced. The PRD is shaped so /speckit-specify can consume it as a feature description.
argument-hint: Optional — extra instructions, scope hints, or an explicit issue number/URL to target
compatibility: Requires `gh` CLI authenticated against the project repo, `dev/constitution.md`, and `.specify/templates/spec-template.md`. Designed to feed `/speckit-specify` afterward.
metadata:
  inspiration: https://github.com/mattpocock/skills/blob/main/skills/engineering/to-prd/SKILL.md
user-invocable: true
disable-model-invocation: false
---

# Create PRD

## User Input

```text
$ARGUMENTS
```

Treat `$ARGUMENTS` as optional scope hints or an explicit issue target. The PRD's content comes from the conversation context, not from arguments.

## What this does

Take the current conversation context plus codebase understanding and produce a **Product Requirements Document**. Publish it to GitHub:

- If an issue was referenced at the start of the conversation → post the PRD as a **comment** on that issue.
- If no issue was referenced → create a **new issue** with the PRD as the body.

Always show the draft to the user and wait for explicit approval before publishing.

**Do NOT interview the user.** This skill synthesises what you already know. If the context is too thin to write a PRD, say so and recommend `/grill-idea` first.

## When to use

- The conversation has produced enough understanding to articulate a feature, and the user now wants it captured as a PRD on GitHub.
- The user explicitly asks for a PRD, a spec writeup, or an issue body.
- A previous `/grill-idea` session produced `.specify/idea-brief.md` and the user wants it turned into a PRD on the tracker.

Do **not** use this skill for:

- Bug reports → use `/create-issue` or the bug-pipeline skills.
- Capturing an idea you have *not* yet stress-tested — run `/grill-idea` first.
- Writing the actual `specs/<n>-<slug>/spec.md` — that is `/speckit-specify`'s job. The PRD produced here is the **input** to `/speckit-specify`.

## Phase 1 — Detect the target issue

Before drafting, decide where the PRD will land. Scan the conversation, **starting from the very first user message**, for any of:

1. A full GitHub issue URL — e.g. `https://github.com/<owner>/<repo>/issues/<N>`.
2. A `#<N>` reference followed by language suggesting it is an issue (not a PR).
3. An explicit phrase like "issue 123", "GH-123", or "the linked issue".

Resolve the candidate:

```bash
gh issue view <N> --json number,title,state,url,labels
```

Decision tree:

- **Exactly one candidate, exists, state = OPEN** → that is the target. Post as a comment.
- **Multiple candidates** → list them to the user with title + state and ask which one.
- **Candidate exists but state = CLOSED** → ask the user whether to reopen + comment, or create a new issue instead.
- **No candidate, or candidate does not exist** → target is a **new issue**. Move on to title/label drafting in Phase 4.

Record the decision before drafting; do not switch targets mid-draft.

## Phase 2 — Repository context

Even when the conversation already gave you most of what you need, do a fast pass to ground the PRD in current project state. Skip a step only if the answer is already in context.

- **Constitution.** Skim `dev/constitution.md` to identify which principles the feature touches. The PRD must call them out explicitly.
- **Domain glossary.** Use Styrmin's canonical vocabulary: `Cluster`, `Environment`, `Deployment`, `Instance`, `Driver`, `Component`, `Workflow`, `ServiceError`. Never introduce synonyms when an existing term fits.
- **ADRs.** Glance at `dev/adr/` for prior decisions in the area the feature touches. Honour them; if the feature contradicts one, surface that as an open question rather than overriding silently.
- **Existing specs.** Check `specs/` for in-flight or recent work touching the same surface. Reference relevant ones in the PRD (`see specs/NNN-…`).
- **Existing labels.** `gh label list --limit 100` once, to pick triage labels that actually exist.
- **AGENTS map.** `backend/AGENTS.md`, `frontend/AGENTS.md`, `python_sdk/AGENTS.md`, `driver/DRIVERS.md` to spot which components the feature touches.

## Phase 3 — Sketch the modules (deep, testable)

Before writing the PRD, list the modules you expect to build or modify. Actively look for opportunities to extract **deep modules** — units that encapsulate substantial functionality behind a small, stable, testable interface that rarely changes. Shallow modules (one-method wrappers, pass-throughs) are anti-patterns.

For each module note:

- Layer (`GraphQL schema`, `service`, `repository`, `driver`, `frontend hook`, `CLI command`, `SDK binding`, …) — per Constitution §III.
- Whether it is **new** or an **extension** of an existing module.
- The one-sentence responsibility.
- Whether it deserves its own unit-test suite, or is covered by an existing one.

Present the module sketch to the user and confirm:

1. Do these modules match your mental model?
2. Which ones do you want unit-tested in their own right? (The others still go through E2E per Constitution §V.)

Wait for confirmation before drafting the PRD body. This is the only point in the skill where input is required from the user beyond final approval.

## Phase 4 — Draft the PRD

Use the template below. Every section is mandatory unless the body explicitly says it can be omitted. Keep the prose tight — a clear three-line section beats a sprawling one.

Apply these rules while drafting:

- **No file paths or code snippets** describing implementation — those rot fast and belong in `/speckit-plan`. Exception: if a prior prototype produced a tight artefact that encodes a decision more precisely than prose (a state machine, a Pydantic schema shape, a GraphQL fragment, a reducer), inline the decision-rich parts and note that it came from a prototype. Trim hard.
- **Use Styrmin domain terms.** No "the thing that deploys" — say `Driver`. No "the deployed app" — say `Deployment` or `Instance`, whichever the conversation pinned down.
- **Make every "MUST" testable.** If a sentence cannot be paired with a single-sentence verification idea, sharpen it.
- **Success Criteria are user-facing and measurable.** No framework names, no millisecond response times — translate to user value ("results in under 1 second", "operator can recover an environment in under 5 minutes").
- **Mirror `.specify/templates/spec-template.md` structure** where possible, so `/speckit-specify` can lift sections wholesale.

### PRD template

```markdown
# PRD: <short feature name>

## Problem Statement

<The problem the user faces, from the user's perspective. Two to four sentences. No solutions yet.>

## Solution Overview

<The proposed solution, from the user's perspective. What changes for them, in plain language. Not how it is built.>

## User Stories

<A long, numbered list. Format: "As a <role>, I want <capability>, so that <benefit>."
Cover every aspect of the feature including admin / failure / observability paths.
Use Styrmin actor vocabulary where possible: platform engineer, application owner, deployer, operator, end-user of a deployed application.>

1. As a platform engineer, I want …, so that …
2. As an application owner, I want …, so that …
3. …

## User Journeys (prioritised)

<Mirror spec-template's P1/P2/P3 structure. Each journey must be an independently shippable slice.>

### P1 — <title>
- Journey: <one sentence end-to-end>
- Acceptance: **Given** <state>, **When** <action>, **Then** <outcome>

### P2 — <title> (optional)
…

### P3 — <title> (optional)
…

## Functional Requirements

- **FR-001**: System MUST …
- **FR-002**: Users MUST be able to …
- **FR-003**: …

## Key Entities

<Map each new or affected concept to an existing Styrmin entity. Flag genuinely new entities explicitly.>

- **Cluster / Environment / Deployment / Instance / Driver / Component / …**: <how the feature affects it>
- **<NewEntity>** *(new)*: <lifecycle, ownership, relationships> — call out for governance review

## Edge Cases

- <Boundary / failure / concurrency / partial-state scenarios — at least three.>

## Success Criteria

- **SC-001**: <measurable, technology-agnostic outcome>
- **SC-002**: …

## Implementation Decisions

<Module-level decisions, schema shapes, API contracts, interaction patterns. NO file paths, NO code unless a prototype encodes a decision more precisely than prose can. If inlining, trim to the decision-rich parts only.>

- Modules to build / modify (from Phase 3 sketch):
  - `<Module name>` (`<layer>`, new|extends): <one-sentence responsibility>
  - …
- GraphQL surface:
  - New fields / arguments / input types / mutations under `backend/styrmin_backend/api/schema/`: <list, or "none">
- Service-layer errors:
  - New `ServiceError` subclasses + `error_code` values: <list, or "none">
- Driver / reconciliation:
  - Does this require a new Driver capability, a new Component, or a change to the reconciliation diff shape? <yes / no — what>
- Frontend surface:
  - New routes, GraphQL operations, or UI components: <list, or "none">
- SDK / CLI surface:
  - New SDK methods or CLI commands: <list, or "none">

## Testing Decisions

- **What makes a good test here.** <Test external behaviour, not implementation details. One or two sentences scoping the principle for this feature.>
- **Unit tests** (per Phase 3, agreed with user): <list of modules>
- **GraphQL propagation tests** (Constitution §V, non-negotiable for any schema change): <list of fields / mutations, or "N/A — no schema change">
- **E2E scenario** (Constitution §V, non-negotiable for new features): <one-sentence description of the user-visible flow that will be exercised end-to-end>
- **Prior art**: <links / paths to existing similar tests in the codebase, if any>
- **api_only vs ui_only marking**: <plan for which variant this E2E should run as — see AGENTS.md "Dual-entrypoint scope">

## Constitution Alignment

- **§I Declarative state reconciliation**: <how this fits the desired/current diff model; idempotency notes>
- **§II Driver-based deployment** *(if deployment-touching)*: <which driver / component owns the behaviour>
- **§III Layered architecture**: <which layers are touched and how>
- **§IV Type safety & typed errors**: <ServiceError subclasses and error codes — see Implementation Decisions>
- **§V Test-first / E2E required**: <see Testing Decisions — name the E2E>
- **§V GraphQL ↔ DB propagation tests**: <list or "N/A">

## Governance Gates Crossed

<Tick every gate this PRD crosses. AGENTS.md requires explicit discussion before implementation for any ticked box.>

- [ ] Database schema or migration change
- [ ] GraphQL schema modification
- [ ] New dependency
- [ ] CI/CD workflow change
- [ ] Authentication / authorization change

## Assumptions

- <Assumption about users, environment, data, or existing systems>
- …

## Out of Scope

- <Explicit non-goals for v1 — carve aggressively>
- …

## Open Questions

- [NEEDS CLARIFICATION: …]

<Cap at three. If more remain, the PRD is not ready — recommend /grill-idea before publishing.>

## Further Notes

- Related specs: <`specs/NNN-…` cross-references, if any>
- Related ADRs: <`dev/adr/…` cross-references, if any>
- Source of this PRD: <conversation summary in one or two sentences>
```

## Phase 5 — Show the draft and get approval

**Never publish without explicit user approval.** Present the full draft inline, then ask:

- Does the module sketch still match? (If they changed their mind, loop back to Phase 3.)
- Is anything missing, wrong, or scope-creeping?
- Approve to publish?

If the draft has more than three `[NEEDS CLARIFICATION]` markers, do not offer to publish — recommend `/grill-idea` to resolve them first.

## Phase 6 — Publish

### Path A — Comment on the referenced issue

```bash
gh issue comment <N> --body-file /tmp/prd-draft.md
```

After posting, fetch the comment URL and report it. If the issue does not already carry an appropriate triage label (project house-style — confirm via `gh label list`), suggest one to the user but do **not** apply it automatically; commenting on someone else's issue should not re-triage it.

### Path B — Create a new issue

Pick the title and labels from project conventions surfaced in Phase 2.

- **Title**: conventional-commit-style prefix when the project uses it (`feat:`, `chore:`, `docs:` …). Keep under 70 characters.
- **Labels**: choose only from labels that exist (`gh label list`). Typical candidates: a type label (`enhancement` / `feature`), a scope label (`backend`, `frontend`, `sdk`, `driver`), and a triage label if the project has a "ready-for-agent" or equivalent (confirm — do not invent labels).

```bash
gh issue create \
  --title "<title>" \
  --body-file /tmp/prd-draft.md \
  --label "<label1>" --label "<label2>"
```

Report the new issue URL.

## Phase 7 — Hand off to speckit

After publishing, tell the user what to run next:

- `/speckit-specify "$(gh issue view <N> --json body -q .body)"` — feed the PRD into spec generation. Or paste the PRD body manually if the runtime cannot interpolate.
- The PRD's structure (User Journeys, FRs, Key Entities, Edge Cases, Success Criteria, Assumptions) maps directly onto `.specify/templates/spec-template.md`, so `/speckit-specify` should produce a strong first-draft `spec.md` with minimal `[NEEDS CLARIFICATION]` markers.

## Anti-patterns

- **Do not interview.** Synthesise from context. If you cannot, stop and recommend `/grill-idea`.
- **Do not invent labels.** `gh label list` first.
- **Do not auto-re-triage someone else's issue.** Commenting must not silently change labels or state.
- **Do not embed file paths or code snippets** in Implementation Decisions, except the prototype-snippet exception. Those rot. Save them for `/speckit-plan`.
- **Do not write the spec.** This skill produces a PRD. The spec is `/speckit-specify`'s output.
- **Do not skip Constitution Alignment or Governance Gates.** Even if the feature seems UI-only, walk the principles — missing alignment here costs rework at plan time.
- **Do not publish without user approval.** Even if you have permissions.

## Expected outcome

A PRD published to GitHub at a known URL (comment on the referenced issue, or a new issue), with:

- All template sections completed.
- Constitution alignment explicit per §I–V.
- Governance Gates marked.
- ≤ 3 `[NEEDS CLARIFICATION]` markers.
- A named E2E scenario (Constitution §V).
- GraphQL propagation coverage either listed or explicitly marked N/A.
- A clear next step pointing to `/speckit-specify`.
