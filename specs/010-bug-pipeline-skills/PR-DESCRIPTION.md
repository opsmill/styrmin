# PR Description Draft — 010-bug-pipeline-skills

This file holds the body content the reviewer should paste into the implementation PR description on GitHub. Spec artefacts and the smoke-test URLs are filled in here; the reviewer fills the smoke-test boxes after running them post-merge.

---

## Summary

- Add four standalone Claude Code skills under `.agents/skills/` — `bug-analyze`, `bug-fix`, `bug-test`, `bug-review` — implementing a four-stage AI bug-fixing pipeline that runs identically from the local CLI and from CI.
- Add four GitHub Actions workflows under `.github/workflows/bug-agent-*.yml` as **thin wrappers** (checkout + permissions + concurrency + a single `claude-code-action@v1` invocation) that fire on `/bug-*` slash-command issue/PR comments.
- Add a developer guide at `dev/guides/bug-pipeline.md` (FR-027) covering local + GitHub triggers, argument formats, stage chaining, failure paths, concurrency, and troubleshooting.
- Ship two design contracts under `specs/010-bug-pipeline-skills/contracts/` — the analyst-summary YAML schema (inter-stage data contract) and the slash-command protocol (trigger contract).
- Spec artefacts: `spec.md`, `plan.md`, `research.md`, `data-model.md`, `quickstart.md`, `tasks.md`, plus a quality checklist under `checklists/`.

## Test plan

- [X] `yamllint -c .yamllint.yml` passes clean on the four new workflow files.
- [ ] Smoke-test `/bug-analyze` locally per `quickstart.md` §1 (T004) — **deferred to reviewer**.
- [ ] Smoke-test `/bug-fix` locally per `quickstart.md` §2 (T006) — **deferred to reviewer**.
- [ ] Smoke-test `/bug-test` locally per `quickstart.md` §3 (T008) — **deferred to reviewer**.
- [ ] Smoke-test `/bug-review` locally per `quickstart.md` §4 (T010) — **deferred to reviewer**.
- [ ] Smoke-test all four workflows from GitHub comments on a sandbox issue (T016) — **deferred to reviewer post-merge**.

## Constitution §V deviation

This feature is meta-tooling (developer-facing automation; no application code, no GraphQL schema change). Per Constitution §V the new-feature E2E rule applies, but the project's pytest E2E suite (`backend/tests/e2e/`) targets the deployment platform on a real Kind cluster and is not a fit for skills whose user-visible flow is "type a slash command on a GitHub issue → side effect appears on GitHub".

The deviation — `yamllint` automation plus a manual smoke-test procedure documented in `quickstart.md` in lieu of a pytest E2E — is recorded in `plan.md` → Complexity Tracking and was explicitly approved by the reviewer (@damien) during `/speckit-auto-implement` preflight. The approval is captured in `tasks.md` under T002.

## Closes

Closes #206.

## Spec artefacts

The full design and tasks for this feature live at [`specs/010-bug-pipeline-skills/`](../../specs/010-bug-pipeline-skills/) — primarily [`spec.md`](spec.md), [`plan.md`](plan.md), and [`tasks.md`](tasks.md), plus the two contracts under `contracts/` and the smoke-test walkthrough at `quickstart.md`.
