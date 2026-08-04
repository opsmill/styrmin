---
name: design-implement-handoff
description: Implement a Claude Design handoff bundle into this codebase using ONLY the existing component library and design tokens, then visually verify the result against the design before preparing a commit. Use this skill whenever the user mentions a handoff, a handoff bundle, "implement this design", "implementuj handoff", a Claude Design export, or asks to turn a design/prototype into code in this repo. Always use it even for small visual changes — the verification and deviation-handling steps are the point.
---

# Implement Design Handoff

Turn a Claude Design handoff bundle into production-quality code that provably
matches the design and the design system. Never skip verification — an
unverified implementation is an unfinished implementation. Never silently
"solve" a deviation from the design system — deviations follow the Deviation
Protocol below.

## Ground rules (non-negotiable)

1. **Source of truth is the code.** The component library and design tokens in
   this repo win over anything in the handoff.
2. **Only existing components and tokens** — unless the Deviation Protocol
   explicitly concludes otherwise with user approval.
3. **Never guess, never approximate silently.** Every mismatch between the
   handoff and the design system goes through the Deviation Protocol.
4. **Never push.** Prepare the commit; the human reviews and pushes/opens PR.

## Cost & model efficiency

- At the start of the run, after picking the verification mode (Phase 4
  header), state the expected cost profile in one line ("light mode, ~1
  screen — cheap run" / "full mode, DS change — expect a heavy run").
- Model guidance to offer the user (they switch via `/model`): the
  mechanical middle — Phase 3 implementation and the 4b/4d capture-compare
  loop — runs fine on Sonnet; judgment-heavy parts — Deviation Protocol
  decisions, Phase 2 plan on DS changes, final review — benefit from the
  stronger model. If the whole session runs on one model, prefer the
  stronger one for handoffs that touch shared DS code, Sonnet for routine
  screen-level changes.
- Screenshot only what the run needs: never capture unchanged screens
  outside 4d, never re-capture screens already at MATCH.

## Deviation Protocol

Use this whenever the handoff asks for something the design system does not
have, or when implementing it would change shared code. Never proceed past a
deviation without an explicit user decision. Always present the deviation in
this format:

```
DEVIATION FOUND
What the handoff wants: <exact description + reference image crop if useful>
What the design system has: <closest existing options, ranked>
My recommendation: <one option + why>
Options:
  A) Use existing <component/variant/token X> — visual difference: <describe>
  B) Use existing <Y> — visual difference: <describe>
  C) Extend the design system (new variant/token/component) — see impact below
  D) Something else / abort this part
```

Rules per deviation type:

- **Unknown component** (handoff references something with no 1:1 match):
  search the library for the 2–3 closest candidates (by role, not by name —
  a "Chip" may live as "Tag"). Present options A/B with concrete visual
  differences. Option C (create new component) must include: proposed API,
  where it lives, that it needs unit-test coverage (Vitest/RTL) plus a real
  usage in a screen for visual review, and a warning that this is a
  design-system change that should likely be its own PR reviewed by the DS
  owner — offer to split it into a separate branch/commit.
- **Unknown variant or prop** on an existing component: same as above, plus
  check whether the visual effect is achievable by composition of existing
  props before proposing an API change.
- **Off-token value** (color/spacing/size not in tokens): propose the nearest
  token(s) with the delta stated ("handoff: #1A73E8, nearest token:
  color.primary.600 = #1B6FE0, Δ barely perceptible"). Only if the user says
  the new value is intentional, treat it as a token addition = design-system
  change (separate commit, token file + documentation updated).
- **Change to a shared design-system component** (the handoff redesigns e.g.
  Button itself, not just its usage): STOP before implementing. Run a usage
  scan (grep/imports) and report the blast radius: "Button is used in N files
  / M screens." Ask whether the change is (a) intended globally → implement in
  the DS component + flag that all consumers need visual review, ideally its
  own PR; (b) intended only here → propose the correct local mechanism
  (existing variant, wrapper, composition) instead of forking or editing the
  shared component.
- **Stale handoff / drift**: if components or tokens referenced by the bundle
  have changed in the repo since the design sync (compare against current
  source, check git log of the component files vs. bundle date), warn that the
  design was made against an outdated system, list what drifted, and recommend
  re-running /design-sync and re-exporting before continuing. Continue only if
  the user explicitly accepts the drift.
- **Malformed/incomplete bundle** (missing reference images, missing spec):
  do not work from imagination — ask for a re-export.
- **Handoff contradicts the user's message**: the user's message wins, but
  state the contradiction out loud before proceeding.
- **Accessibility regression** (the design lowers contrast below tokens'
  documented contrast pairs, removes focus states, shrinks touch targets):
  flag it as a deviation even though it "matches the design" — design intent
  does not override a11y baselines.

Batch reporting: collect all deviations found in Phase 1 and present them
together as one numbered list, so the user decides everything in one round
instead of being interrupted repeatedly. Deviations discovered later (during
implementation or verification) are presented as they arise.

## Phase 0 — Preconditions

Verify and report:

- [ ] Repo root, clean working tree. If dirty, ask.
- [ ] Feature branch `design/<short-description>` (respect repo conventions if
      they exist — check CONTRIBUTING.md / recent branches).
- [ ] Handoff bundle path provided. If not, ask. Do not guess.
- [ ] Frontend dev server starts. **This repo has NO Storybook** — visual
      verification runs against the running dev server (vite on :5173), not
      Storybook. Ensure the GraphQL port-forward is up so screens have data
      (`kubectl port-forward svc/styrmin-server 8000:8000 -n styrmin`; see
      `project_styrmin` memory and `design-capture-screen`). If the dev server is
      broken before you start, report and stop — never fix unrelated breakage
      inside a handoff implementation.
- [ ] Playwright + Chromium available (Phase 4 depends on it). Ask before
      installing anything.
- [ ] The in-app Browser pane blocks bare `localhost:5173`; open it via
      `preview_start {name:"frontend"}` then navigate the preview tab to the
      preview's actual URL (port 5173 by default; `.claude/launch.json` sets
      `autoPort`, so it may bind another port — use the one `preview_start`
      reports). See `design-capture-screen`.
- [ ] Detect theming: if the repo supports light/dark or multiple themes,
      note it — Phase 4 must verify every theme, not just the default.

## Phase 1 — Read the handoff, build an inventory

Read the entire bundle (spec, README, design notes, reference images). Produce
an inventory table:

| Screen/area | Components (exact library names) | Variants/props used | Tokens involved | Reference image |
|---|---|---|---|---|

Resolve every referenced component to a real file in `frontend/src/components/`
(and its usages, so you know where it renders). Anything that does not resolve
1:1 → Deviation Protocol. Also run the drift check (see protocol) here, while it
is still cheap to stop.

## Phase 2 — Plan

Short implementation plan: files to change, variants/props used, deviations
already decided and their resolution. Ask for confirmation only if the plan
touches shared design-system components or includes an approved DS extension;
otherwise proceed.

## Phase 3 — Implement

- Compose screens from existing components via their public props API — read
  the component's TypeScript types/source and `frontend/AGENTS.md` +
  `dev/guidelines/frontend/ui-primitives.md` for the real API/conventions (there
  is no Storybook); never invent props.
- Minimal diff: no drive-by refactors, no formatting churn.
- **No Storybook in this repo — do NOT add stories.** Instead:
  - where component *behaviour/logic* changed, update or add the repo's unit
    tests (Vitest + React Testing Library), mirroring neighbouring test
    conventions and importing components via the repo's `@` alias;
  - visual states (default, hover, focus, disabled, loading, empty, error —
    whichever apply) are proven in Phase 4 by rendering the real screen in the
    dev server and driving states with Playwright, not by isolated stories;
  - no hardcoded colors or spacing anywhere — tokens only, same rule as
    production code.
- Run lint, typecheck, unit tests. Fix what your change broke; report (don't
  fix) pre-existing failures.

## Phase 4 — Verify (the core of this skill)

Run all checks and report each explicitly. Verification runs headless.

**Verification mode — decide and announce it first.** Visual verification is
the token-expensive part of this skill; scale it to the blast radius:

- **light** (default): 1 primary viewport (1440×900, or the design's target),
  default theme only, changed screens only, max 2 iterations per
  screen. 4d only if shared code was touched (as always).
- **full**: all 3 viewports, all themes, interaction states in 4c, max 3
  iterations. Use when: the diff touches shared DS components, tokens, or
  global styles; the handoff spans multiple screens; responsive behavior is
  part of the design intent; or the user asks for it.

Pick the mode from the diff scope, announce it with one-line reasoning
("light mode: single screen, no shared code touched"), and let the user
override. Never silently downgrade a run that meets a full-mode trigger.
4a and the capture discipline rules apply identically in both modes —
cheap checks are never skipped.

**Evidence directory.** All verification artifacts are saved, not just shown:
create `docs/handoffs/<handoff-name>/` and write everything there —
side-by-side comparison images (`<screen>-<viewport>[-<theme>].png` plus the
matching reference), `token-audit.md`, `deviations.md` (this handoff's
numbered list with resolutions), and `verification-summary.md` (which also
records the verification mode used and why). These files are committed with
the change: the reviewer gets proof, not claims.

### 4a. Token & component audit (static, diff-only)

Scan the diff for: hardcoded colors (hex/rgb/hsl), spacing/size magic numbers
where a token exists, font values outside the type scale, hand-built elements
where a library component exists. Output: finding → file:line → suggested fix.
Apply fixes, re-scan until clean. Off-token values that were user-approved via
the Deviation Protocol are listed as "approved exceptions", not findings.

### 4b. Visual comparison (rendered, semantic — not pixel matching)

1. Start the dev server (vite :5173, with the GraphQL port-forward up so screens
   have data). There is no Storybook — a component-scoped change is verified on
   the real screen(s) that render the component, not in isolation.
2. Screenshot changed screens with Playwright at the viewport(s) the
   verification mode dictates (full: 375×667, 768×1024, 1440×900).
   **Capture discipline:** wait for actual content readiness, not
   `networkidle` — assert that expected text/elements are present in the DOM
   and no skeletons/spinners are visible before capturing. If the framework
   hydrates (React/Vue/…), wait for hydration to complete. Retry capture once
   if the assertion fails; if it fails twice, report instead of comparing a
   half-rendered page.
3. Themes per the verification mode (full: every theme at the primary
   viewport, all viewports for the default theme).
4. Compare each screenshot against the handoff reference image **semantically,
   element by element**: layout structure, spacing rhythm, colors, typography,
   component variants, states. Do not use pixel-diff as the judge — it is
   brittle; use it at most as a hint for where to look. For each screen output
   MATCH or DIFFERS with a concrete difference list, and for each difference
   say which side is correct per Ground rule 1 (or whether it is an approved
   deviation).
5. Iterate implement → re-capture until MATCH or only user-approved
   differences remain. Hard limit per the verification mode (light: 2,
   full: 3 iterations per screen), then stop and
   present the side-by-side to the user to arbitrate.

### 4c. Computed-style spot checks

Screenshots miss layout mechanics. For key changed elements, use Playwright
`evaluate` to assert computed styles the design depends on: flex/grid
behavior, rendered widths at each breakpoint, gap values resolving to the
expected token, z-index stacking, focus-visible styles present. List each
assertion and its result. If the change involves interaction states, drive
them (hover/focus via Playwright) and capture those states too.

### 4d. Regression guard (unchanged consumers must stay unchanged)

4a–4c prove the changed screens match the design. This step proves nothing
else changed. Run it whenever the diff touches a shared design-system
component, a token file, or global styles — i.e. whenever the Deviation
Protocol's blast-radius scan found consumers outside this feature.

1. Build the baseline: check out the base branch in a separate worktree
   (`git worktree add ../<repo>-baseline <base-branch>`), install deps if
   needed, and serve its dev server on a separate port. Never use stash-juggling
   on the working branch for this.
2. Screenshot the real screens/routes that render the blast-radius consumers in
   both baseline and current branch (same capture discipline as 4b), at the
   primary viewport. (No Storybook — drive the app routes that use each consumer.)
3. Compare pairs. Screens changed **by intent** (listed in the Phase 1
   inventory) are exempt. Every other pair must be visually identical; any
   difference is an unintended regression — fix it or, if it turns out to be
   a necessary consequence of an approved DS change, present it via the
   Deviation Protocol as a newly discovered deviation.
4. Save the pairs with differences (and a one-line verdict per consumer) into
   the evidence directory as `regression-<component>.png` +
   `regression-summary.md`. Remove the worktree when done.

If the diff touches no shared code, state that 4d was skipped and why.

## Phase 5 — Prepare the commit

- Stage only files related to this handoff (including the evidence
  directory). If an approved design-system extension happened (new
  variant/token/component), put it in a **separate commit** (or offer a
  separate branch/PR) from the feature usage.
- **Deviation log (team feedback loop):** append every deviation from this
  handoff to the global `docs/handoffs/deviations.md` — date, handoff name,
  deviation type, what the design wanted, resolution (A/B/C/D). One line per
  deviation, newest on top. Recurring entries in this log are the
  data-backed backlog for design-system evolution; never skip the append.
- **PR description:** generate `docs/handoffs/<handoff-name>/pr-body.md`
  ready to paste into the PR — summary of the change, the deviation table
  with resolutions, verification results (4a–4d) with relative links to the
  evidence images, and viewports/themes covered.
- Conventional commit message; body lists screens changed, deviations and how
  they were resolved, and a one-line verification summary.
- Do NOT push. Final report in the conversation:
  1. What changed (files + summary)
  2. Deviations found and their resolutions (numbered, matching Phase 1 list)
  3. Verification results (4a/4b/4c/4d, pass/fail each, themes/viewports
     covered), with the evidence directory path
  4. Anything requiring human review (esp. DS changes and their blast radius)
  5. Suggested next step (open PR with the generated pr-body.md / hand to dev
     team / re-run design-sync if the DS was extended, so the design side
     stays in sync)

## Failure handling summary

- Deviation without user decision → never proceed.
- Verification stuck after 3 iterations → stop, show evidence, ask.
- Broken environment (dev server won't start, missing Playwright) → report, stop.
- When in doubt between "quietly make it work" and "ask" → ask. This skill's
  value is trustworthiness, not speed.
