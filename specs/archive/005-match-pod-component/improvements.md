# Improvement Recommendations: Reducing CI Churn for Future Spec Work

**Context:** companion to `session-summary.md`. The 005-match-pod-component PR took 5 CI runs and ~3.5h end-to-end. ~1h45m of that was pure CI time. Most of the friction came from a small number of structural gaps in the repo that are concrete, documented, and fixable.

This document is **opinionated**. The goal is "what's the least amount of process that prevents the most CI churn" — not a wishlist.

---

## Highest-impact gaps (fix these first)

### 1. Hand-written translations between layers are an ergonomic landmine

**Symptom in this session:** the same shape of bug appeared 3 times — a new field plumbed through Pydantic / SQLModel / Strawberry was silently dropped at hand-rolled dict-builder seams.

| Site | What it does | Caught by |
|---|---|---|
| `SQLModelPodStatusRepository.upsert` | Mutates an existing row attribute-by-attribute | Pre-PR code review |
| `report_pod_statuses` resolver in `api/schema/mutation.py:756` | Hand-builds the dict passed to the service layer | 4th CI run, only after a custom diagnostic log |
| `StyrminClient.deployments` resource methods | Curated SDK facade — every query needs a method added | 1st CI run, `AttributeError` |

**Why this keeps happening:** each of these sites is a translation between two systems that already have full schemas (Pydantic / SQLModel / Strawberry). The translation is hand-rolled, so it doesn't pick up new fields automatically.

**Recommendations (pick one or more):**

- **Mechanize the translations.** Replace hand-built dict comprehensions with `dataclasses.asdict(input)` or equivalent. The existing field-list-by-hand pattern is the bug factory.
- **Or, add a structural test** that asserts every field on `PodStatusInput` is present in the dict the resolver passes to the service. Same for the upsert. A simple introspection-based test would catch these.
- **Or, document this as a hazard in `AGENTS.md`.** A short list: "If you add a field to `PodStatus`, you must also update: (1) the Strawberry input/output, (2) the mutation resolver dict at `mutation.py:768`, (3) `SQLModelPodStatusRepository.upsert`, (4) the SDK resource method, (5) the agent's Pydantic model. The fake repo in tests must mirror the SQL upsert, or it will mask omissions."

The first option is the strongest — eliminates the bug class. The third is the cheapest — a 6-line addition to `AGENTS.md` would have prevented at least 2 of the 3 bugs in this session.

### 2. Alembic migration head collisions are detectable in 5 seconds

**Symptom in this session:** my migration's `down_revision` matched another existing migration's `down_revision`, producing two heads. `alembic upgrade head` would have failed once the branch met `develop`. Caught in pre-PR review by reading commit history; would otherwise have surfaced post-merge.

**Recommendation:**

- **Add a pre-commit hook** that runs `alembic heads` and fails if the count is ≠ 1. Five-second check.
- **Or, document in `AGENTS.md`** under "Database schema or migration changes" that you must run `alembic heads` before pushing. The "Ask First" section already mentions migrations but doesn't say *what to check*.

### 3. The SDK has a curated facade, not a generated public API

**Symptom in this session:** I assumed `client.X.method` came from the auto-generated `python_sdk/src/styrmin_sdk/graphql/_generated/client.py`. It doesn't — the public `StyrminClient` is a hand-curated facade via `Resource` classes. Adding a new query requires writing a method on the matching resource. **This is not documented anywhere.**

**Recommendation:**

- Add a section to `AGENTS.md` (or `python_sdk/AGENTS.md` if it exists, which it doesn't yet — that's also a gap) explaining the SDK pattern:
  - `client.<resource>.<method>` calls go through `_transport.execute()` + a `.graphql` file
  - Adding a new query requires (a) the `.graphql` file, (b) `uv run invoke generate`, (c) a method on the matching `Resource` class
  - Generated code under `_generated/` is not the public surface

---

## Documentation gaps

### 4. `PodStatus` is not documented in `dev/knowledge/`

`dev/knowledge/backend/data-models.md` covers most platform models but `PodStatus` is missing — has been since it was added in spec 001-agent-status-reporting. This isn't fatal, but it means anyone touching pod-status reporting has no reference doc and ends up reading code.

**Recommendation:** add a `#### PodStatus` subsection under "Deployment Models" in `data-models.md`. Cover: what it represents (observed runtime state, not declared intent — link ADR-007), what fields it has, how it's populated (agent's reporter loop), and what nullable means at this layer.

### 5. `uv run invoke generate` silently requires `pnpm install` first

**Symptom in this session:** I ran `invoke generate` after editing GraphQL queries; it generated Python types but failed on the frontend codegen step with `sh: graphql-codegen: command not found` — because `frontend/node_modules/` wasn't installed.

**Recommendation:**

- Either make `invoke generate` skip the frontend step gracefully if `node_modules` isn't present (with a warning), or add a clear note to `AGENTS.md` under "Setup" that `cd frontend && pnpm install` is a prerequisite.

### 6. The `dev-validate` skill is not advertised

The `dev-validate` skill ("Idempotently spin up the full Styrmin dev environment, run tests, deploy a Semaphore application, and verify everything works end-to-end including the frontend") is exactly what someone working on E2E-touching changes wants to know about, but it's not mentioned in `AGENTS.md`. I almost used it during this session and only didn't because I wasn't sure if it was the right tool.

**Recommendation:** mention it in `AGENTS.md` under "Debugging E2E Tests" or in a new "Local Validation" section. Frame it as the path for "run the full E2E loop locally before pushing to avoid CI roundtrips."

---

## Testing gaps

### 7. No tests exist at the GraphQL mutation resolver layer

The resolver bug in `api/schema/mutation.py:768` was structurally invisible to:
- Unit tests (didn't reach the resolver)
- Service-layer tests (resolver wasn't in the call path)
- Repository tests (resolver wasn't in the call path)

The E2E test caught it, but at the cost of two full CI runs (~45 minutes) plus custom diagnostic instrumentation.

**Recommendation:** add a thin layer of resolver-level tests using Strawberry's test client. They don't need a real DB — they can use `FakeUnitOfWork`. The value is asserting "every input field reaches the service-layer dict", which is exactly the bug class that escaped unit and integration coverage in this session.

### 8. Fake repositories can silently mask field-omission bugs in real repos

**Symptom in this session:** the SQL upsert was missing `component_name`, but the fake repo's `upsert` did a wholesale row replacement, so the unit tests passed. Caught in pre-PR review by reading both implementations side-by-side.

I fixed this for `FakePodStatusRepository` (mirrored the SQL pattern in commit 15cb320). But the same risk exists for every other `Fake*Repository` in `backend/tests/unit/services/fakes.py`.

**Recommendation:** an audit pass over `fakes.py` to ensure every fake `upsert` mirrors the field-by-field mutation pattern of its real counterpart, OR a structural test that compares the two using introspection.

---

## Tooling / process gaps

### 9. E2E feedback is 20+ minutes per iteration

This is the single biggest source of wall-clock cost in any PR that touches E2E-relevant code. There's no way to short-circuit it — even when 95% of the change is purely additive and the failure is in one specific layer.

**Recommendations (tradeoffs):**

- **Document a `dev-validate` workflow** as the local equivalent of E2E (see #6 above). Cuts roundtrip from 20 min to ~10 min if the cluster is already up.
- **Allow targeted re-runs of just the failed E2E test from a CI artifact.** Currently a full re-run is 20 min even to retry one test. A `--last-failed` mode against an already-running CI cluster would be transformative.
- **A "thin E2E" pattern for additive features** — e.g., a fast E2E that asserts on existing SDK responses for an existing deployment without redeploying. Adding a field is a strong candidate for this pattern.

### 10. The `@pytest.mark.api_only` convention isn't obvious

The dual-entrypoint E2E setup runs every test twice — once under `api-chromium` and once under `ui-chromium`. My pod-component test doesn't exercise any UI flow (it only uses the SDK client and kr8s), but I didn't mark it `api_only` and it ran twice. That's a free 50% reduction in E2E time for tests that don't need the UI variant.

**Recommendation:** in `AGENTS.md` under E2E debugging, add: "If your test doesn't drive a UI flow (only uses the SDK and Kubernetes APIs), mark it `@pytest.mark.api_only` so the UI variant is skipped." A grep against existing tests would identify candidates already in the suite that could benefit retroactively.

### 11. Diagnostic patterns are ad hoc

Each CI failure prompted a custom one-off diagnostic — kr8s pod-label snapshot in the test, then an `INFO` log inside the agent. These were effective but the next investigator will reinvent them.

**Recommendation (optional, cheaper):** when a diagnostic proves valuable enough to ship, leave a comment in the test file naming the pattern. Future devs grep for "diagnostic" and have a starting point. Over time this becomes a small library of probe patterns.

---

## What worked well — keep doing this

These are the positive side of the session. Worth preserving:

1. **The pre-PR code review by an independent agent caught two real bugs** (SQL upsert, migration heads). It's worth its weight; the SQL upsert in particular would have been a confusing post-merge bug since unit tests would have stayed green.
2. **The constitution's "E2E is part of done" rule is what kept the resolver bug from shipping.** Without it, I would have merged with green unit tests and the bug would have surfaced in production.
3. **Diagnostics-first debugging** — every CI iteration added a targeted instrumentation step that turned the next run into fact-finding. Three of the five CI runs were specifically to gather data, not to ship a fix. That's the right tradeoff at 20 min per run.
4. **Capturing architectural decisions in ADRs alongside the spec** (ADR-007 in this case) means the *why* is stored next to the *what*. Future maintainers won't have to reconstruct it from commit messages.

---

## Quick-action list (prioritized)

If you can only do a few things, in order of return on effort:

1. **Add a pre-commit hook for `alembic heads` ≠ 1** — 30 min to write, prevents one full CI cycle every time someone branches and forgets to rebase their migration.
2. **Add a "fields pass-through" structural test for the `report_pod_statuses` resolver** — 30 min to write, would have caught the bug that cost ~45 min of CI time in this session, plus ~30 min of debugging.
3. **Document the SDK facade pattern in `AGENTS.md`** — 15 min, prevents the `AttributeError`-class CI failure for any future query addition.
4. **Document `dev-validate` as the local E2E loop in `AGENTS.md`** — 5 min, accelerates every future E2E iteration.
5. **Audit `fakes.py` for `upsert` symmetry with real repos** — 1 hour, eliminates a class of false-positive unit tests.
6. **Add `PodStatus` to `dev/knowledge/backend/data-models.md`** — 20 min, opportunistic doc fix.

Items 1–4 alone would likely have cut this session from 5 CI runs to 2, and from ~3.5h to ~1.5h.
