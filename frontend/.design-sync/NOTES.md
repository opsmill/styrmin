# design-sync notes — styrmin frontend

Repo-specific gotchas for `/design-sync` (package shape). Read before every re-sync.

## The core reality: `frontend` is an app, not a packaged component library
- `frontend/package.json` is `private`, `version: 0.0.0`, **no `exports`**, and its
  `dist/` is the **Vite app build** (assets + index.html), not importable components.
- The package-shape converter assumes the DS is an installed package at
  `node_modules/<pkg>` and reads its shipped `.d.ts`. Neither exists here.

## Workarounds applied (to make the run go at all)
- **Self-symlink** `node_modules/frontend -> frontend` so `PKG_DIR` resolves
  (`ln -sfn "$(pwd)" node_modules/frontend` from `frontend/`). Types are absent, so
  the export scan returns empty (no crash) and synth-entry takes over.
  Gitignored → **recreate on every fresh clone**.
- **synth-entry mode** (no dist entry) — the converter synthesizes the bundle from
  `src/`. `cfg.srcDir` is narrowed to **`src/components/ui`** so the synth entry
  bundles only the primitives, not the whole app.
- **`cssEntry` MUST be the COMPILED Tailwind CSS** (`dist/assets/index-<hash>.css`),
  NOT `src/index.css`. Tailwind v4 utilities (`bg-primary`…) are build-generated and
  are NOT in source — using `src/index.css` ships components unstyled.
  ⚠️ The hash filename changes on every `pnpm build` and is machine-specific, so the
  committed `config.json` holds a **placeholder glob** (`dist/assets/index-*.css`), NOT a
  real path. The `design-sync-check` skill resolves the actual hashed file (`ls
  dist/assets/index-*.css`) and patches `cfg.cssEntry` locally before each sync — never
  commit the resolved hash back.

## Quality limitations of the current output (honest)
- **Weak prop contracts.** synth-entry + no shipped types → `<Name>Props` extracts to
  `{ [key: string]: unknown }` (e.g. `ButtonProps`). The design agent's API contract is
  effectively empty. Not fixable without a real lib build that emits `.d.ts`.
- **49 components, not 16.** The ui primitives PLUS every sub-export (CardHeader,
  DialogClose, SelectTrigger…). Prune to the ~16 primaries with `componentSrcMap: {"CardHeader": null, …}` if a clean set is wanted.
- **No docs matched (0/49)** → minimal `.prompt.md`. **Floor cards only** (no authored previews).

## Re-sync risks
- `cfg.cssEntry` hash is build-specific — stale after any `pnpm build`.
- Prop contracts stay weak until the components are a real buildable package.

## Recommendation (for the team)
To make `/design-sync` first-class, extract `frontend/src/components/ui` into a real
buildable package with `dist/` + `exports` + emitted `.d.ts` (and ideally Storybook for
verification). That removes the self-symlink hack, the synth-entry weak types, and the
compiled-CSS-hash fragility all at once.

## Update — authored previews + page naming (fixes empty floor cards)
- Authored `.design-sync/previews/<Name>.tsx` for all 16 components (import from
  bare `'frontend'` — the story-imports shim maps it to `window.StyrminUI.*`).
  Cards now render live, styled components with realistic Styrmin content.
  Render check: 16/16 clean, 0 blank, 0 floor cards.
- **Tooltip**: exported wrapper doesn't forward `defaultOpen` → popup is hover-only,
  card shows only the trigger. Toaster: runtime-only toasts → card shows a placeholder.
  Both acceptable; a `cardMode`/provider override could improve them later.
- **Page cards**: the app self-check names cards by FILENAME. Pages were
  `pages/<x>/index.html` → all showed as "index". Renamed to `pages/<x>/<Name>.html`
  (e.g. Environments.html) so they get real names. Do NOT use index.html for pages.
  (Pages are the capture-screen artifact, not produced by the built-in converter.)
- Durable/committable now includes `.design-sync/previews/*.tsx` (16) + config + NOTES.

## Fixes — checkbox collapse + overlay cropping
- **Checkbox** (Base UI) collapses to a ~1px sliver when rendered bare in a cell.
  Fix: author each cell inside `<div style={{display:'inline-flex',alignItems:'center',gap:8}}>`
  with a Label sibling — then it renders as a proper 16px box. (A lone `<Checkbox/>` in a
  preview cell = broken-looking; always give it flex context.)
- **Select / DropdownMenu / Dialog** portal their open content to document.body, which the
  DS pane's fixed-size card CLIPS. Fix: `cfg.overrides.<Name> = {"cardMode":"single",
  "primaryStory":"Open","viewport":"WxH"}` (in config.json) so the open state renders in a
  single full-card view with room. `[GRID_OVERFLOW]` in validate flags exactly which need this.
- **Dialog** `DialogContent` hardcodes a `bg-black/80` backdrop that fills the whole
  static card. Neutralize it in the preview with an injected
  `<style>.bg-black\/80{background:transparent!important}</style>` so the panel floats
  cleanly on the card. (Select/DropdownMenu popups have no dark backdrop — only Dialog.)
