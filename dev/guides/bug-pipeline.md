# Bug-Fixing Pipeline

The bug-fixing pipeline is a human-gated, four-stage AI-assisted flow for taking a reported bug from triage to a reviewed pull request. styrmin runs the **shared** pipeline hosted in [`opsmill/opsmill-cicd-workflows`](https://github.com/opsmill/opsmill-cicd-workflows): the agent logic lives there as the single source of truth, and styrmin commits only a relay, a test profile, and the four worker workflows installed from the central catalog.

All four stages run **on styrmin's own runners** with styrmin's **own `GITHUB_TOKEN`** — no cross-repo dispatch. The test and fix stages execute styrmin's tests locally (write a failing test → run → prove red; apply the fix → run → prove green). styrmin's ordinary CI check on the draft PR is the reviewer's empirical proof gate.

This pipeline does **not** replace the general-purpose `@claude review` workflow in `.github/workflows/claude.yml`; that stays as the catch-all reviewer.

## What styrmin hosts

| File | Role | Edit? |
|------|------|-------|
| `.github/workflows/bug-pipeline-relay.yml` | The dispatcher. Listens for slash commands + PR CI conclusions, enforces the approval gate, dispatches the matching worker locally. Generic and **identical across every consumer**. | Verbatim — never customize |
| `.github/workflows/bug-agent-{analyst,test,review,fix}.{md,lock.yml}` | The four workers, installed from the central catalog via `gh aw add`. The `.md` is a bot-managed stub; the `.lock.yml` is `gh aw compile` output. | Never by hand — refreshed via `gh aw update` PRs |
| `.github/bug-pipeline/profile.yml` | styrmin's executable test profile (base branch, authoritative check, setup/test/format/lint commands). Consumed by the test/fix workers. | Yes — repo-specific values |
| `.github/labels.yml` | Declares the four `state/*` pipeline labels (synced by the `Sync Labels` workflow). | Yes |

The worker sources of truth live centrally at `workflows/bug-agent-*.md`; styrmin carries bot-managed copies. The gh-aw toolchain version is pinned in `.github/aw/actions-lock.json` (currently v0.86.2).

## The four stages at a glance

```
/bug-analyze ─► analyst  ─► root-cause comment        (AGENT_ANALYSIS_COMPLETE)
/bug-tdd     ─► test     ─► draft PR w/ failing test  (AGENT_TEST_COMPLETE)
 (CI concludes) ─► reviewer ─► verdict comment        (AGENT_REVIEW_VERDICT: TEST_APPROVED)
/bug-fix     ─► fixer    ─► fix commits on the PR     (AGENT_FIX_COMPLETE)
 (CI concludes) ─► reviewer ─► verdict comment        (AGENT_REVIEW_VERDICT: FIX_APPROVED) ─► human merges
```

The pipeline is **test-first**: `/bug-tdd` opens a draft PR whose new test *fails* — a **red** `Unit Tests` check on the test-only PR is the *expected* signal that the bug reproduces. `/bug-fix` then makes it pass. Each transition is driven by a maintainer's slash command and gated by the marker the prior stage left; the reviewer is not a slash command — it fires automatically when CI concludes on a pipeline PR.

## How to trigger

1. On a bug **issue**, a maintainer adds the `state/ai-pipeline-ready` label. This is the approval gate — without it, every command is silently ignored.
2. Comment `/bug-analyze` → the analyst posts a root-cause analysis.
3. Comment `/bug-tdd` → the test-writer opens a draft PR (branch `ai-bug-pipeline-*`) with a failing regression test. When CI concludes, the reviewer auto-runs and should post `TEST_APPROVED`.
4. Comment `/bug-fix` **on the pull request** → the fixer pushes the fix; CI goes green; the reviewer auto-runs and posts `FIX_APPROVED`. A human merges.

The trigger matcher is strict: the comment's first token must be exactly `/bug-analyze`, `/bug-tdd`, or `/bug-fix` (a blockquote or mid-paragraph mention will not fire). Only actors with a write-ish role (`OWNER`/`MEMBER`/`COLLABORATOR`) can run it. `/bug-fix` must be run on the PR, not the issue.

If a stage can't proceed safely it stops and applies a `state/needs-human-*` label with an explanation instead of advancing.

### The state labels

| Label | Meaning |
|-------|---------|
| `state/ai-pipeline-ready` | Approval gate — the pipeline may act on this issue/PR |
| `state/need-more-info` | Analyst needs more information to proceed |
| `state/needs-human-test` | The test stage could not proceed and needs a human |
| `state/needs-human-fix` | The fix stage could not proceed and needs a human |

## Identity & security model

The shared App private key is never in scope of a code-executing (or any agent) job:

- **The relay** runs with `permissions: {}` and per-job `actions: write` / `contents: read`, using styrmin's own `GITHUB_TOKEN`. It holds **no** App key and **no** `ANTHROPIC_API_KEY`.
- **Each worker's agent job** (the one that runs the engine and executes styrmin's tests) runs **read-only** (`contents`/`issues`/`pull-requests: read`) with `GITHUB_TOKEN` + `ANTHROPIC_API_KEY` only.
- **`BUG_PIPELINE_APP_ID` / `BUG_PIPELINE_APP_PRIVATE_KEY`** are referenced **only** inside each worker's isolated safe-output jobs (`conclusion`, `safe_outputs`), which mint a short-lived App token and write back as `opsmill-bug-pipeline[bot]` (needed for marker attribution and to trigger CI on the draft PR).

## Prerequisites (org / repo configuration)

- **Org secrets**, restricted to onboarded repos and available to styrmin: `BUG_PIPELINE_APP_ID`, `BUG_PIPELINE_APP_PRIVATE_KEY`, `ANTHROPIC_API_KEY` (used **by the workers**, not the relay).
- **The `opsmill-bug-pipeline` GitHub App** installed on styrmin.
- **Actions variable** `GH_AW_GITHUB_APPROVAL_LABELS=state/ai-pipeline-ready` — **required**. Without it, the workers' `min-integrity: approved` read filter blocks reading an approved issue and the agent stops.

  ```bash
  gh variable set GH_AW_GITHUB_APPROVAL_LABELS --body 'state/ai-pipeline-ready'
  ```

## Maintaining the installed workers

The workers are bot-managed installs — **never hand-edit** the `.md` stubs or `.lock.yml` artefacts. Updates from the central catalog arrive as `gh aw update` PRs. If you ever need to recompile locally (e.g. after a gh-aw version bump), do it by path and re-approve the manifest:

```bash
gh aw compile --approve   # records any new secrets/actions in .github/aw/actions-lock.json — review first
```

`yamllint` ignores `.github/workflows/*.lock.yml` (configured in `.yamllint.yml`), and `.gitattributes` marks them `linguist-generated`.

To re-onboard from scratch (or add a consumer), follow the central operator guide at [`docs/docs/bug-pipeline/readme.md`](https://github.com/opsmill/opsmill-cicd-workflows/blob/main/docs/docs/bug-pipeline/readme.md) and the styrmin recipe at [`docs/docs/bug-pipeline/styrmin.md`](https://github.com/opsmill/opsmill-cicd-workflows/blob/main/docs/docs/bug-pipeline/styrmin.md):

```bash
gh aw add opsmill/opsmill-cicd-workflows/bug-agent-analyst
gh aw add opsmill/opsmill-cicd-workflows/bug-agent-test
gh aw add opsmill/opsmill-cicd-workflows/bug-agent-review
gh aw add opsmill/opsmill-cicd-workflows/bug-agent-fix
```

## Local human-facing skills

The interactive skills `.agents/skills/bug-{analyze,tdd,fix}` remain — they are the human-facing variant of the method, invokable directly from a Claude Code session in the repo. The pipeline itself no longer runs them; it runs the central catalog workers.

> The method intentionally lives in two places — the central worker prompts (pipeline) and the local skills (humans) — maintained separately.

## The test profile

`.github/bug-pipeline/profile.yml` is composed from the central `compose.py base python-uv node-pnpm` and then edited to match styrmin:

- `base_branch: develop` — the branch pipeline PRs target.
- `authoritative_checks: [Unit Tests]` — the backend pytest CI job (`unit-tests` in `ci.yml`, surfaced as the **Unit Tests** check) that proves fail→pass.
- `setup` / `runners` / `format` / `lint` — styrmin's real invocations (`uv sync`, `uv run invoke format|lint`, and the `cd frontend && pnpm …` tasks) that the local test/fix agents run.

## Troubleshooting

- **Command doesn't fire** — the comment's first token must be exactly the command (`/bug-tdd`, not `/bug-tddx` or `> /bug-tdd`), the actor must have write access, and the issue/PR must carry `state/ai-pipeline-ready`.
- **Worker stops immediately / can't read the issue** — confirm the `GH_AW_GITHUB_APPROVAL_LABELS` variable is set (see Prerequisites).
- **`Unit Tests` is red after `/bug-tdd`** — that is the expected signal on a test-only PR (the bug reproduces). It should go green after `/bug-fix`.
- **Reviewer didn't run** — it fires on `check_suite: completed` for `ai-bug-pipeline-*` branches; confirm CI actually concluded on the PR.
- **A `state/needs-human-*` label appeared** — the stage stopped and needs a human; read the accompanying comment for what blocked it.

## References

- Central operator guide: [`docs/docs/bug-pipeline/readme.md`](https://github.com/opsmill/opsmill-cicd-workflows/blob/main/docs/docs/bug-pipeline/readme.md)
- styrmin onboarding recipe: [`docs/docs/bug-pipeline/styrmin.md`](https://github.com/opsmill/opsmill-cicd-workflows/blob/main/docs/docs/bug-pipeline/styrmin.md)
- Placement rationale: ADR-0016 (uniform consumer-side placement) in the central repo.
- Local skills: [`.agents/skills/bug-analyze/SKILL.md`](../../.agents/skills/bug-analyze/SKILL.md), [`.agents/skills/bug-tdd/SKILL.md`](../../.agents/skills/bug-tdd/SKILL.md), [`.agents/skills/bug-fix/SKILL.md`](../../.agents/skills/bug-fix/SKILL.md)
- Historical (pre-central) design: [`specs/archive/010-bug-pipeline-skills/`](../../specs/archive/010-bug-pipeline-skills/)
