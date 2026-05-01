# Quickstart: Verifying the Python SDK AGENTS.md feature

**Feature**: 001-sdk-agents-md
**Date**: 2026-05-01

This is a documentation-only change. Verification is by review against the
spec's acceptance criteria, plus a few mechanical checks.

## Prerequisites

- A checkout of the `001-sdk-agents-md` branch.
- Repo root in working directory.

## Mechanical checks

```bash
# 1. The new file exists.
test -f python_sdk/AGENTS.md && echo OK || echo MISSING

# 2. The root AGENTS.md references python_sdk/AGENTS.md in two places.
grep -c 'python_sdk/AGENTS.md' AGENTS.md
# Expected: 2 (one in File Structure, one in Component Maps)

# 3. The "regen is not enough" callout is present in the SDK doc.
grep -i 'regenerat.*not enough\|not enough.*regen\|does not auto-wire\|not automatic' python_sdk/AGENTS.md
# Expected: at least one match — the explicit warning required by FR-003.

# 4. The three regen commands are documented in the SDK doc workflow.
grep -E 'styrmin export graphql-schema|invoke generate|invoke validate-graphql' python_sdk/AGENTS.md | wc -l
# Expected: 3

# 5. The "Always Do / Ask First / Never Do" headings are present.
grep -E '^### (Always Do|Ask First|Never Do)$' python_sdk/AGENTS.md | wc -l
# Expected: 3

# 6. Markdown lints clean (project-wide).
uv run invoke format lint
```

## Review checklist

Walk the spec's acceptance scenarios end-to-end:

- [ ] **US1-S1**: SDK doc names and describes `client.py`, `_transport.py`,
      `_queries.py`, `resources/`, `graphql/`, `graphql/_generated/`.
- [ ] **US1-S2**: Root `AGENTS.md` references `python_sdk/AGENTS.md` in
      both **File Structure** and **Component Maps**.
- [ ] **US2-S1**: SDK doc explicitly states that adding the `.graphql` file
      and regenerating types is not enough — Python code must be updated
      by hand.
- [ ] **US2-S2**: The three regen commands appear in the workflow in the
      correct order.
- [ ] **US2-S3**: A worked example snippet shows `load_query()` + generated
      Pydantic validation together.
- [ ] **US3-S1**: An "Always Do / Ask First / Never Do" section exists,
      structurally analogous to the root.
- [ ] **US3-S2**: "Never Do" lists "edit files under `graphql/_generated/`".
- [ ] **US3-S3**: "Ask First" mentions transport changes, new dependencies,
      and public client API surface changes.

## Smoke test (optional, for a future contributor following the doc)

Pretend you are an agent asked to add `client.deployments.get_timeline()`
backed by a hypothetical `getDeploymentTimeline` operation. Open
`python_sdk/AGENTS.md` and follow the workflow. You should naturally:

1. Create `python_sdk/src/styrmin_sdk/graphql/get_deployment_timeline.graphql`.
2. Run the three regen/validate commands.
3. Add `async def get_timeline(self, ...)` to `resources/deployments.py`.
4. Use `load_query("get_deployment_timeline")` and `_check_graphql_errors`
   exactly like the worked example.
5. Add a test.

If any of those steps requires reading source code instead of the doc, the
doc is incomplete and must be revised.

## Out of scope (not verified here)

- Behavior changes to the SDK runtime — this feature does not introduce any.
- Updates to `dev/` knowledge or ADRs — those are extracted in
  `/speckit.extract` (Phase 6).
