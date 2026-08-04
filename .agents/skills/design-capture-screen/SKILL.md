---
name: design-capture-screen
description: Capture a live application screen from the running app and push it into the Claude Design project as an editable, self-contained page snapshot (group "Pages"), reproduced ONLY from components and tokens that actually exist in the synced design system — never invented. Use whenever the user wants to design against a whole existing screen (not just isolated components) — "capture this page", "snapshot the deployment detail screen into Claude Design", "I want to redesign a real page". Complements design-sync-check (which syncs the component library); this skill handles full-page compositions.
---

# Capture Screen → Claude Design

Reproduces a **live application screen** as an editable, self-contained HTML page
and pushes it into the same Claude Design project the component library lives in,
under a top-level `pages/` group. The designer then edits the screen in Claude
Design; `design-implement-handoff` maps the change back onto real components + tokens.

## Mental model — read this first

- The **component library** (see `design-sync-check`) is the canonical source of
  truth / vocabulary. This skill does NOT touch it.
- A **screen capture is a disposable, dated snapshot** of a composition (real
  components + real data + a viewport). It rots the moment the code or data
  changes. **Regenerate it fresh every time** — never maintain it as canonical.
  Stamp the capture with the date and the app commit it came from.
- Screens do not replace components. When a captured screen is edited and handed
  back, the implementation still resolves to edits in real component/page code.

## NON-NEGOTIABLE: build only from the real design system — never invent

This is the whole point of the skill. A capture that quietly invents a component,
colour, radius, or spacing is WORSE than no capture, because the designer will
design against a lie and the handoff will not map back.

1. **Load the real inventory first** (see Prerequisites §4). You must know exactly
   which components and which tokens exist in the synced design system before you
   build anything.
2. **Every element you render must map to a real DS component or a real token.**
   Colours, radii, font sizes, shadows, spacing → use the token values, not
   hand-picked approximations. Interactive blocks (button, badge, card, input,
   tabs, dialog…) → reproduce the real component's classes/variants, nothing else.
3. **Do NOT fabricate.** If the screen shows a control or style you cannot trace
   to a real component/token, you may not "make something close up". Instead,
   record it as a **deviation**.
4. **Report deviations and ask before pushing** (see Workflow §6). Never resolve a
   deviation silently. Two common kinds:
   - *Not-in-DS component*: the screen uses a composition that isn't a synced
     component (e.g. an app-shell sidebar, a page-specific card, a status pill
     that isn't the `badge` component). List it; ask whether to (a) treat it as a
     page-local element rendered from tokens only, (b) add it to the component
     library first via `design-sync-check`, or (c) omit it.
   - *Off-token style*: a colour/spacing/radius on the live page that does not
     match any token (a drifted hard-coded value). List it with the actual value
     and the nearest token; ask whether to snap to the nearest token or flag it as
     a code bug to fix separately. Do NOT bake the off-token value into the capture
     without a decision.

## Honest limitations (state these to the user up front)

1. **A screen is only as good as the app state you capture it from.** Empty lists,
   missing seed data, or a Pending/error state will be reproduced faithfully — if
   the page needs data to be meaningful, seed it (or pick a populated page) first.
2. **A reconstructed HTML page is "close", not guaranteed pixel-perfect.** The
   pixel-perfect alternative is embedding a PNG screenshot, but that is not
   editable in Claude Design. This skill deliberately chooses editable HTML built
   from real components + tokens over a static image.

## Prerequisites (verify or stop on each)

1. **A component sync already exists** for this project (run `design-sync-check`
   first if not) — the screen must reuse the same components and tokens.
2. **The dev stack is running.** Check before starting anything: `colima status`,
   `kubectl get pods -n styrmin`, and whether the vite dev server + the
   `port-forward svc/styrmin-server 8000:8000` are alive (`pgrep -fl vite`,
   `pgrep -fl "port-forward.*styrmin-server"`). See `project_styrmin` memory for
   the full local-dev recipe. Do not re-provision what is already up.
3. **A private, user-owned Claude Design project** to push into. NEVER push
   screens into a shared/team project without explicit confirmation.
4. **Load the real DS inventory** (mandatory — this is what prevents invention):
   - Components: `DesignSync list_files` on the target project → the `components/`
     paths tell you which components exist. Cross-check against the code component
     library (`frontend/src/components/ui/`).
   - Tokens: read the real token source (`frontend/src/index.css` `@theme` block).
     These token values are the ONLY palette/spacing/radius vocabulary allowed.
   Keep this inventory in hand for the reconciliation step.

## Workflow

### 1. Open the running app in the browser pane
- The in-app Browser pane blocks a bare `localhost:5173` navigation by policy.
  Work around it: `preview_start {name:"frontend"}` to open a preview tab, then
  `navigate` that tab to `http://localhost:5173` (localhost works *inside* the
  preview tab). If `preview_start` collides on a stale port (known 7777 clash),
  just navigate the already-open preview tab.

### 2. Authenticate — the USER logs in, never the agent
- If the app shows the login screen, STOP and ask the user to sign in themselves
  in the preview tab (username is `admin`; the password is their local dev password —
  `STYRMIN_ADMIN_PASSWORD` if set, else the random one logged at boot — ask them, don't
  assume `styrmin`). Do not type passwords —
  entering credentials to authenticate is prohibited. The in-app browser has its
  own session, separate from the user's real Chrome.

### 3. Navigate to the target screen and confirm it has data
- Routes are SPA routes (e.g. Environments is `/`, not `/environments`). Use
  `read_page` to get real nav hrefs; click the ref rather than guessing URLs.
- If the page is empty and empty isn't the point, seed data or pick another page.

### 4. Capture the reference (resolution matters)
- Set a real desktop viewport BEFORE capturing: `resize_window {width:1440,height:900}`.
  Narrow viewports clip toolbars/buttons and produce a misleading capture — always
  capture and later verify at the same explicit width, never at a squeezed pane
  default. If the design system targets other breakpoints too, capture each
  breakpoint you intend to publish (e.g. 1440 desktop, 768 tablet) as separate
  cards; do not guess responsive behaviour from one width.
- Take a full screenshot (visual truth).
- Extract exact values with `javascript_tool`: computed colours, font, radii,
  paddings, border colours, box-shadows, and the class names of every key block
  (sidebar, header, cards, badges, buttons…).

### 5. Reconcile against the DS inventory, THEN build
- For every captured element, map it to a real component or token from §4.
  Build the page using ONLY those. Reproduce component variants from their real
  source classes; use token values verbatim.
- Collect everything that does NOT map into a **deviation list** (see the
  NON-NEGOTIABLE section). Do not invent a substitute for a deviation.
- File: one `.html` at `pages/<screen-name>/<Name>.html` (e.g.
  `pages/environments/Environments.html` — NOT `index.html`, see §8 naming); first line MUST be
  `<!-- @dsCard group="Pages" -->`; inline ALL CSS (token block + real component
  styles); no external resources.

### 6. Report deviations and get a decision — before pushing
- Present the deviation list to the user: each item, what it is, why it doesn't
  map to the DS, and the options (page-local from tokens / add to DS / omit; or
  snap-to-token / flag-as-bug for off-token styles). Wait for the decision and
  apply it. If there are no deviations, say so explicitly.

### 7. Verify — before pushing
Two gates. The programmatic one is mandatory and reliable; the visual one is
best-effort (rendering is often blocked in this environment).

**7a. Programmatic gate (MANDATORY, always works).** Two cheap checks:
```
grep -oE '\-\-[a-z-]+:' f.html | sed 's/://' | sort -u > /tmp/def
grep -oE 'var\(--[a-z-]+\)' f.html | sed -E 's/var\((.*)\)/\1/' | sort -u > /tmp/use
comm -23 /tmp/use /tmp/def   # MUST be empty
```
This proves **no dangling token references** (every `var(--x)` resolves in the file's
own `:root`) — it is a lint, NOT proof of fidelity: an invented value inlined into
`:root` would still pass. For real no-invention proof, spot-check the inlined `:root`
values against `frontend/src/index.css` (they must match). Also assert: line 1 is the
`<!-- @dsCard group="…" -->` marker. **Do NOT** grep for a literal `class="active"`
(the real `AppShell` marks the active item with conditional Tailwind — `bg-primary
text-primary-foreground` — there is no `active` class; asserting one would fail a
faithful capture or push you to invent it). External-resource check: flag only actual
fetches — `src="http`, `href="http`, `<link `, `<script ` with a URL, `@import url(http`
— and **exempt inline SVG/XML namespaces** (`xmlns="http://www.w3.org/2000/svg"` on
lucide-style inline icons is NOT an external ref). Fix any real failure before pushing.

**7b. Visual gate (best-effort).** Render at the SAME width as step 4 and compare
side-by-side with the live page. `file://` and `data:` URLs are usually blocked in
the pane and `preview_start` with a file URL can hang; the base64-inject trick
(`document.open();document.write(decodeURIComponent(escape(atob(B))));document.close();`
in the app tab, then navigate back to restore) works but is FRAGILE for large
files — a single mis-paste truncates it. Verify the shell ONCE on the first screen
you build (they all reuse it verbatim), then rely on 7a for the rest. Do not block
the push on 7b if the shell is already visually verified and 7a passes.

### 8. Push
- **Name each page file `<Name>.html`, NOT `index.html`.** The app's server-side
  self-check names each card by its emitted **filename** (+ the `@dsCard group="…"`
  header). `pages/<slug>/index.html` therefore shows as "index"; use
  `pages/<slug>/<Name>.html` (e.g. `pages/environments/Environments.html`) so cards
  get real names. (This is the durable fix — verified in practice.)
- `finalize_plan` with `writes:["pages/**", "_ds_needs_recompile"]`, `deletes:[]`,
  `localDir` = bundle dir. Same project as the components; the `pages/` group keeps
  screens visually separate from `components/`.
- Upload order: **write `_ds_needs_recompile` (sentinel) → `write_files` the pages →
  re-write `_ds_needs_recompile`.** The sentinel is what triggers the app's self-check
  to re-index cards on next project open — **that**, not any manual file, is why new
  pages appear. Then tell the user to refresh.
- **Do NOT hand-edit or push `_ds_manifest.json`.** The app regenerates
  `ds_manifest` server-side from the uploaded source (`@dsCard` markers) on every
  project open; a hand-authored copy is bogus work that gets overwritten. If pages
  don't show after a refresh, the cause is a missing/awry sentinel or a bad
  `@dsCard` first line — never a manifest that needs patching.

### 9. Record
- Note in the capture (and to the user) the date and the app commit hash it was
  taken from, plus any deviations and how they were resolved.

## Cadence
- Run on demand, right before a design session on a specific screen.
- Re-run (regenerate) rather than editing an old snapshot — snapshots always drift.
