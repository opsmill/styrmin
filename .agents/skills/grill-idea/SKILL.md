---
name: grill-idea
description: Relentless interview-style session that stress-tests a raw feature idea against the Styrmin constitution and existing domain, producing a PRD-ready brief that can be handed straight to /speckit-specify. Use when the user has a fuzzy idea and wants to harden it before writing a spec.
argument-hint: A short description of the idea to grill (optional — if absent, ask once for the seed idea)
compatibility: Requires `dev/constitution.md` and `.specify/templates/spec-template.md`. Designed as the pre-step before `/speckit-specify`.
metadata:
  inspiration: https://github.com/mattpocock/skills/blob/main/skills/engineering/grill-with-docs/SKILL.md
user-invocable: true
disable-model-invocation: false
---

# Grill Idea

## User Input

```text
$ARGUMENTS
```

Treat `$ARGUMENTS` as the seed idea. If empty, ask the user for it once before starting the interview.

## What this does

Interview the user relentlessly about every aspect of a feature idea until it is ready to be turned into a spec by `/speckit-specify`. Walk down each branch of the idea tree, resolving dependencies between decisions one-by-one. For each question, propose your recommended answer first, then wait for feedback before asking the next one. If a question can be answered by reading the codebase, the constitution, or existing specs, do that instead of asking.

The output is a written **idea brief** under `.specify/idea-brief.md` that mirrors the structure of `.specify/templates/spec-template.md` closely enough that `/speckit-specify` can consume it as a strong feature description.

## When to use

- The user has an idea expressed in one or two paragraphs and wants a spec.
- The idea is fuzzy on scope, users, success, or how it fits the existing system.
- The user explicitly says they want to grill / stress-test / pressure-test an idea before specifying it.

Do **not** use this skill for:

- A bug fix or refactor with no user-visible behaviour change — go straight to `/speckit-tinyspec-tinyspec` or a regular PR.
- An idea the user has already turned into a spec — use `/speckit-clarify` instead.

## How to interview

- **One question at a time.** Do not batch. Wait for an answer before the next question.
- **Lead with your recommendation.** Format each turn as: short context → question → your recommended answer with reasoning → invite confirmation or redirection.
- **Explore before asking.** If the codebase, `dev/constitution.md`, `dev/knowledge/`, `dev/adr/`, or existing `specs/` can answer the question, read them and report findings rather than asking.
- **Cross-reference with code.** When the user asserts how something works today, verify against the relevant files in `backend/`, `frontend/`, `python_sdk/`, or `driver/`. Surface contradictions immediately.
- **Sharpen fuzzy terms.** When the user says "deployment", "environment", "cluster", "driver", "instance" — pin down which existing domain entity they mean. Use the project's canonical vocabulary, not synonyms.
- **Use concrete scenarios.** When relationships are vague, invent a specific example ("imagine a user upgrades driver v1.2 → v1.3 mid-reconciliation — what should happen?") and force a precise answer.
- **Capture clarifications inline.** Update `.specify/idea-brief.md` as decisions land. Don't batch at the end.

## Grilling lenses

Every idea must be grilled along these lenses, in this order. Skip a lens only if you can justify why it does not apply.

### 1. Users and value

- Who is the primary user? (developer, platform engineer, end-user of a deployed app, internal operator?)
- What can they not do today, or what is painful?
- What is the smallest observable change that would make them say "this is better"?

### 2. User journeys (P1/P2/P3)

The spec template requires **prioritized, independently testable** user stories. Pin down at least one P1 journey before considering the idea grilled. Each story must be a slice that could ship on its own and still deliver value.

- What is the P1 journey end-to-end? (single sentence)
- Is there a P2 / P3? If yes, can each be developed, tested, deployed, demoed independently?
- For each: write a **Given / When / Then** acceptance scenario before moving on.

### 3. Functional requirements

- What MUST the system do that it does not do today? Express as testable `System MUST …` statements.
- What MUST users be able to do? (`Users MUST be able to …`)
- For every "MUST", ask: how would you verify this in a test? If you cannot describe a test, the requirement is not yet testable — sharpen it.

### 4. Key entities and domain fit

- Which existing entities are touched? (`Cluster`, `Environment`, `Deployment`, `Instance`, `Driver`, `Component`, `Workflow`, etc.)
- Are any new entities required, or can the idea be expressed in terms of existing ones? Strongly prefer the latter.
- If a new entity is needed: what is its lifecycle, who owns it, and what is its relationship to existing entities?

### 5. Edge cases

- Boundary conditions (empty, max, concurrent, partial).
- Failure modes (network, validation, permission, reconciliation drift).
- "What happens when … ?" — invent at least three scenarios and force an answer for each.

### 6. Success criteria

The spec template demands **measurable, technology-agnostic** outcomes (`SC-001`, `SC-002`, …). Push the user past vibes:

- Replace "faster" with "in under N seconds".
- Replace "more reliable" with "P99 success rate ≥ X%".
- Replace "easier" with a task-completion metric or a reduction in support load.
- Reject criteria that name a framework, library, database, or response-time-in-ms (those are implementation, not user value).

### 7. Constitution alignment

`dev/constitution.md` defines non-negotiable principles. Use them as grilling questions, not as a checklist to ignore. For each principle below, ask: does this idea respect it, or does it push back on it? If it pushes back, surface that explicitly — it may need to become an Assumption, a Governance Gate decision, or a reason to reshape the idea.

- **§I Declarative state reconciliation.** Can the new behaviour be expressed as desired-vs-current diff, or does it want imperative side effects? Idempotent?
- **§II Driver-based deployment.** If the idea touches how an app is deployed, does the behaviour belong in a driver, or is it sneaking ad-hoc deployment logic outside drivers?
- **§III Layered architecture.** Where does each new responsibility sit — GraphQL, service, repository, DB? Any cross-layer shortcuts being proposed?
- **§IV Type safety & typed errors.** What new `ServiceError` subclasses are needed? What `error_code` values? Any failure mode that currently has no typed error?
- **§V Test-first / E2E required.** Sketch the E2E scenario name. What user-visible flow does it cover? If the idea is "too small for E2E", challenge that — the constitution treats E2E as definition-of-done for new features and requires explicit reviewer approval to skip.
- **§V GraphQL ↔ DB propagation tests.** Does the idea introduce any new GraphQL field, argument, input type, or mutation? If yes, a propagation unit test is mandatory.
- **§VI Format and lint.** (No grilling needed at idea stage.)

### 8. Governance gates ("ask first" areas)

Surface these explicitly and confirm the user wants to take them on, because they require explicit discussion before implementation per `AGENTS.md`:

- Database schema or migration changes.
- GraphQL schema modifications.
- New dependencies.
- CI/CD workflow changes.
- Authentication / authorization changes.

For each gate the idea crosses, name it in the brief under **Governance Gates Crossed** so it is impossible to miss at the spec stage.

### 9. Assumptions and out-of-scope

- What is being assumed about users, environment, data, or existing systems?
- What is explicitly **out of scope** for v1? (Carve scope aggressively — a small, sharp spec is better than a sprawling one.)
- What dependencies on other in-flight specs (`specs/*`) exist?

## Capture format

Maintain `.specify/idea-brief.md` throughout the session. Create it on the first decision, not before. Use the structure below — it mirrors `.specify/templates/spec-template.md` so `/speckit-specify` can lift sections wholesale.

```markdown
# Idea Brief: <short name>

**Status**: Grilling | Ready for /speckit-specify
**Seed**: <one-paragraph original idea>

## Users and Value
<who, what pain, what better looks like>

## User Journeys
### P1 — <title>
- Journey: …
- Given / When / Then: …
### P2 — <title> (optional)
…

## Functional Requirements (draft)
- FR-001: System MUST …
- FR-002: Users MUST be able to …

## Key Entities
- <Entity>: <role, relationships> — existing | new

## Edge Cases
- …

## Success Criteria (draft)
- SC-001: <measurable, tech-agnostic>

## Constitution Alignment
- §I Declarative: <how the idea fits / where it pushes back>
- §III Layered: …
- §IV Typed errors: <new ServiceError codes proposed>
- §V E2E coverage: <one-line description of the E2E scenario this feature will ship with>
- §V GraphQL propagation: <yes/no — and which fields if yes>

## Governance Gates Crossed
- [ ] Database schema change
- [ ] GraphQL schema change
- [ ] New dependency
- [ ] CI/CD change
- [ ] Auth change

## Assumptions
- …

## Out of Scope (v1)
- …

## Open Questions
- [NEEDS CLARIFICATION: …]
```

Mark unresolved items as `[NEEDS CLARIFICATION: <specific question>]`. The next step (`/speckit-specify`) is allowed at most three of these — if the brief has more, keep grilling until you are down to three or fewer.

## Stop conditions

The brief is "Ready for /speckit-specify" when **all** of the following hold:

1. At least one **P1 user journey** with a Given / When / Then acceptance scenario.
2. Functional requirements are testable — every "MUST" can be paired with a one-line verification idea.
3. Success criteria are measurable and technology-agnostic.
4. The constitution alignment section names the **E2E scenario** that will be shipped, even if just as a sentence.
5. Every Governance Gate the idea crosses is explicitly checked or explicitly ruled out.
6. No more than three `[NEEDS CLARIFICATION]` markers remain.

When all six hold, flip **Status** to `Ready for /speckit-specify`, tell the user, and recommend running `/speckit-specify` with the brief as input.

## Anti-patterns

- **Do not grill into implementation.** Stack choices, schema column names, libraries, file paths — those belong in `/speckit-plan`, not here. If a question can only be answered by picking an implementation, defer it.
- **Do not invent edge cases the user has not signalled care about.** Stress-test the boundaries the idea actually touches, not a generic checklist.
- **Do not stall on perfect requirements.** Three crisp testable FRs that ship is better than ten that don't.
- **Do not skip the constitution lens.** Even if the idea seems UI-only, walk §I–§VI explicitly — the constitution is the project's non-negotiable contract and missing alignment here costs rework at plan time.
- **Do not write the spec.** This skill produces a brief, not a spec. The spec is `/speckit-specify`'s job.

## Expected outcome

`.specify/idea-brief.md` exists, has `Status: Ready for /speckit-specify`, and contains enough sharpened content that `/speckit-specify "$(cat .specify/idea-brief.md)"` (or an equivalent paste) produces a high-quality first-draft `spec.md` with at most three `[NEEDS CLARIFICATION]` markers.
