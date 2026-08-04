---
name: design-sync-check
description: Safely run the built-in /design-sync between this repo's component library and Claude Design — verify prerequisites before syncing and verify the sync's fidelity afterwards. Use whenever the user wants to sync the design system, run /design-sync, push components to Claude Design, mentions sprint-start/sprint-end design sync, or complains that components in Claude Design don't match the code. Also use after any merged change to shared components or tokens, to decide whether a re-sync is needed.
---

# Design Sync Check

Wraps the built-in `/design-sync` with pre-flight and post-flight checks so the
design side is always built on a verified, current component bundle. A bad sync
poisons every design made after it — this skill exists to make bad syncs
impossible to miss.

**Styrmin reality (read `frontend/.design-sync/NOTES.md` first):** the frontend has
**no Storybook**, and `frontend` is an **app, not a packaged component library**. So
`/design-sync` runs in the **package shape**, and specifically its **synth-entry**
fallback. Verification is a **headless render check + absolute-rubric grading** — there
is **no Storybook, no screenshot compare loop, no reference render**. Do not expect or
require any of those.

**All 16 primitives already ship authored, committed previews** (`frontend/.design-sync/previews/*.tsx`,
part of the durable set) — so the **expected post-flight is 0 floor cards**. A floor card
appearing for a component that HAS an authored preview is a **regression** (its `.tsx`
failed to compile), NOT the deliberate baseline — chase it, don't accept it.

## When re-sync is needed (quick decision)

If asked "do we need to re-sync?", check git since the last sync (`docs/handoffs/last-sync.md`
if present, else ask):

- shared component source (`frontend/src/components/ui/`) changed → re-sync
- token files (`frontend/src/index.css` `@theme`/`.dark`) changed → re-sync
- an authored preview (`frontend/.design-sync/previews/*.tsx`) changed → re-sync
- new component/variant added → re-sync (author its `.design-sync/previews/<Name>.tsx`
  first, or accept the honest floor card — there are **no stories** in this repo)
- only app screens / non-DS code changed → no re-sync

Report the verdict with the changed DS files as evidence.

## Pre-flight (before running /design-sync)

Verify, fix, or stop on each:

1. **Clean tree, base branch, up to date** — syncing from a feature branch publishes
   unreviewed components to every future design. If not on the base branch, stop and
   confirm intent.
2. **Config present & honest** — `frontend/.design-sync/config.json` should pin
   `shape: "package"`, the `srcDir` scope + `componentSrcMap` exclusions, and a `cssEntry` pointing at the
   **compiled Tailwind CSS** (`frontend/dist/assets/index-<hash>.css`, produced by
   `pnpm build`), NOT `src/index.css` (Tailwind v4 utilities are build-generated, so a
   source CSS ships components unstyled).
   ⚠️ **The committed `cssEntry` is a placeholder glob (`dist/assets/index-*.css`) — it is
   NOT a real path.** The content hash changes on every `pnpm build` and is machine-specific,
   so it must never be hard-coded in the shared config. **Resolve it at sync time:** run
   `pnpm build` (from `frontend/`), then auto-detect the real file and patch the config
   locally before syncing — e.g.
   `css=$(ls -1 dist/assets/index-*.css | head -1) && ` update `cfg.cssEntry` to that exact
   path in your working copy. Do this on every run; do NOT commit the resolved hash back.
   If more than one `index-*.css` exists, `pnpm build` left stale assets — clean `dist/`
   and rebuild so exactly one matches.
3. **App-not-lib caveat is expected** — synth-entry means the emitted `<Name>.d.ts`
   prop contracts come out **weak** (`[key: string]: unknown`). That is a known
   limitation, not a bug to chase; the real fix is extracting `ui/` into a buildable
   package (see NOTES). Don't block the sync on it — just make sure the team knows.
4. **Playwright + Chromium for the render check** — used for the headless render check
   (the package-shape verification). It's **install-or-skip**, not mandatory: if a
   matching chromium isn't cached, ask before installing (~200MB); the sync may proceed
   with `--no-render-check` **only** with explicit user sign-off, and you must report
   renders as machine-unchecked.

Report a pre-flight summary (pass/fail per item) before proceeding.

## Run the sync

Run the real built-in `/design-sync` from the repo root. During the run:

- **HARD RULE — run the real command, never fake it.** This skill's job is to run the
  genuine `/design-sync` and wrap it with checks; it does NOT reimplement the sync. Run the
  genuine skill (or, if you can't invoke it in this session, have the user type
  `/design-sync`). If it isn't available, **STOP and say so** — do not substitute.
  **NEVER** hand-build static HTML preview cards via the raw `DesignSync` tool and pass
  them off as a sync: static cards are NOT the real importable component bundle
  (`_ds_bundle.js` of the compiled components) that the built-in produces, and shipping
  them silently gives the team an inferior, misleading design system. (This exact
  substitution happened once — don't repeat it.)
- Review the plan (files/components it will write or delete) and summarize it before
  approval. Deletions of components that still exist in the repo are a red flag — stop.
- **Shape is package (no Storybook) — that's correct here.** The absence of a compare
  loop is expected. What you must not accept silently is an *unverified* bundle (render
  check skipped without sign-off, or grading not done).

## Card naming & the manifest (do it right)

- Cards are named by the **emitted filename** + the first-line `<!-- @dsCard group="…" -->`
  marker. The converter emits `components/<group>/<Name>/<Name>.html`, so component cards
  are named correctly by construction. (Only hand-authored pages at `<slug>/index.html`
  would mis-name as "index" — that's the `design-capture-screen` skill's concern, and its
  fix is filename `<Name>.html`, not manifest edits.)
- **Never hand-author the card manifest.** The app regenerates it server-side
  (`ds_manifest`, surfaced in the project as `_ds_manifest.json`) from the uploaded
  source (`@dsCard` markers) on project open, triggered by the `_ds_needs_recompile`
  sentinel (the converter writes the sentinel at build time; the sync uploads/re-arms
  it). A hand-authored manifest is bogus work that gets overwritten — and don't confuse
  it with `_ds_sync.json`, the sync's verification anchor.

## Post-flight (after the sync)

1. **Render-check report** — from `ds-bundle/.render-check.json`: list components and
   whether each rendered clean vs. flagged `bad`. **Expected here: 0 floor cards** (all 16
   primitives have authored previews). A floor card that appears for a component with an
   authored `.tsx` is a **regression** (preview failed to compile) — chase it, don't accept
   it. (In general — for an unauthored component — a floor card is a deliberate baseline, not
   a failure; that's just not the case for Styrmin's 16 today.) Note: on an anchored re-sync
   the driver may *scope* the render check, so `.render-check.json` can be sampled/absent —
   for a 16-component DS the full check always runs, so this doesn't apply here.
2. **Grade / spot-check** — package shape grades on the **absolute rubric** (styled /
   complete / plausible), not against a reference. Eyeball `ds-bundle/.review.html`
   (iframes every card) and the capture sheets in `_screenshots/review/`; confirm the
   high-traffic components (Button, Input, Card, …) look right.
3. **Record the sync** — write/update `docs/handoffs/last-sync.md`: date, commit synced
   from, component count, floor-card components, and any `[FONT_MISSING]`/weak-contract
   caveats. Commit it. (`docs/handoffs/` exists; `last-sync.md` is greenfield.)
4. **Recommend follow-ups** — fix any regressed preview (a floor card that shouldn't be
   there); the extract-`ui/`-into-a-package work (fixes weak contracts); and whether designers should
   re-export in-flight handoffs made against the previous sync (drift rule — see
   `design-implement-handoff`).
5. **Nudge — stale captured screens.** If captured screens are being maintained in this
   project (via `design-capture-screen`) and this sync changed a component or token, the
   screens that use it may now be stale. Recommend re-capturing the ones actively being
   designed against. This is a reminder only — do NOT auto-run `design-capture-screen`, and
   do NOT try to patch the screens in place. Screens are disposable snapshots: regenerate
   them fresh, never sync them.

## Cadence

- Sprint start: re-sync so designers work with current components.
- Sprint end / after merging any DS change: re-sync so the design side reflects what shipped.
- Either way, run both flights. Never "just quickly sync" — the checks are cheap, a
  poisoned sync is not.
