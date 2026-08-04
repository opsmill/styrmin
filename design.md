# Styrmin — Design

> **Status:** Draft v0.5 (research-verified, consistency-polished; not yet reviewed/ratified) · **Owner:** _unassigned_ · **Last updated:** 2026-07-27
> **Supersedes:** nothing. Complements the docs in [§13](#13-relationship-to-existing-documents--enforcement).

<!--
  ONE design doc, two altitudes:
    Part A = product & system design (WHY Styrmin exists, scope, shape) — HUMAN-facing.
    Part B = design language (HOW the UI looks & behaves) — the AGENT-facing piece.
  DURABLE context, NOT a per-feature spec. It NEVER reproduces values that live in
  code/other docs — it links. Source of truth: token VALUES → frontend/src/index.css ;
  system detail → dev/knowledge/architecture.md + dev/adr/. If this file disagrees with the
  source, the source wins — fix this file. Keep it lean (Part B ≤ ~3k tokens); prune on drift.
  `TODO` = needs a team decision before this stops being a draft.

  AGENT USAGE: attach/point agents at PART B only (it stands alone and stays under the
  length budget); Part A is human framing and would just be context noise for a design→code
  agent. Enforcement is layered: this doc (rules) + Tailwind v4 @theme (utilities constrain
  output to real tokens) + visual verification (§13).
-->

---

# Part A — Product & system design  *(human-facing framing)*

## 1. Purpose & audience
Styrmin is OpsMill's **deployment-orchestration platform**: it declaratively deploys,
backs up, upgrades and reconciles a *stack* of applications on Kubernetes via versioned
**application drivers**. Part A gives the "why/what shape" in one read (summarizing, and
linking to, the detailed docs — never restating them). **Audience:** new contributors,
partners/reviewers before a major change. (Part B is the UI design language — for everyone
building UI, human or agent.)

## 2. Problem
An automation stack (a source of truth like [Infrahub](https://opsmill.com/), config tooling
like Ansible, observability like Grafana/Prometheus) must be deployed, backed up, upgraded and
rehearsed **together**. By hand that's a Helm chart, a bespoke backup script, and a
tribal-knowledge upgrade runbook *per app* — with no safe way to rehearse against
production-like data first. **Premise:** encode "how to operate this app correctly" once,
per app, as a versioned artifact (the **application driver**), applied consistently across
clusters, environments and the whole lifecycle. `TODO`: product-owner review of framing.

## 3. Goals
Full-lifecycle management (deploy/configure/back up/upgrade/restore/clone) of a *stack* as one
system · "the right way to operate app X" as a **declarative, versioned artifact** · **clone**
an environment (incl. prod data) to rehearse upgrades · **idempotent & self-healing**
(reconciling a converged system is a no-op; Constitution §I) · managed experience **without
day-to-day Kubernetes expertise**.

## 4. Non-goals (today)  `TODO`: confirm with product/eng
**Multi-cluster** (one cluster at a time by design — [ADR-039](dev/adr/0039-single-cluster-platform-scope.md)) · a **general-purpose GitOps engine** (uses FluxCD underneath; doesn't replace Argo/Flux) · **replacing apps' own config surfaces** · **full driver coverage now** (only the Infrahub driver ships in-repo).

## 5. Ecosystem
Built by [OpsMill](https://opsmill.com/) (makers of **Infrahub**, the infrastructure
data-management platform for network automation & AI). Infrahub et al. are the
**workloads**; Styrmin is the **lifecycle/operations layer** that runs them — a sibling, not a
competitor. Scoping rule: "how to model branches" is Infrahub's; "how to back up Infrahub's
store during an upgrade" is ours. Family voice/values worth inheriting: source-of-truth,
versioning-for-everything, git-native branching/review/rollback (§11) — see
[docs.infrahub.app](https://docs.infrahub.app/) for how the sibling product talks about itself.

## 6. System shape (summary — detail lives elsewhere)
A **server** (FastAPI + GraphQL + PostgreSQL — owns DB/API, decides *what should run*) and a
per-cluster **agent** (Prefect worker + `kopf` operator + status reporter — the only thing
touching Kubernetes). The server never calls the agent; it writes **recorded intent** (a flow
run / a `StyrminDeployment` CRD) the agent picks up (crash-safety + decoupling). Declarative
state at two layers (Deployment vs. Instance; CRD vs. cluster); config is a hierarchical
`GlobalContext` frozen at reconcile time.
→ Detail: [`dev/knowledge/architecture.md`](dev/knowledge/architecture.md); **alternatives
considered for each decision** live in the individual [`dev/adr/`](dev/adr/) entries (e.g.
why single-cluster — [ADR-039](dev/adr/0039-single-cluster-platform-scope.md#alternatives-considered));
principles in [`dev/constitution.md`](dev/constitution.md). *(Deliberately not restated here —
a design doc should link to trade-off records, not re-litigate them.)*

---

# Part B — Design language (UI)  *(agent-facing; attach THIS as context; ≤ ~3k tokens)*

**Brief.** Styrmin's UI is a **dense, calm, information-first operations dashboard** for
infrastructure/platform engineers — utilitarian, legible, and on-brand with the Infrahub
family. Favour clarity and state visibility over decoration.

Durable rules for how the UI looks & behaves. **Values are NOT reproduced here** — token
values live in `frontend/src/index.css` (`@theme` = light, `.dark` = dark); component
APIs/measurements in `frontend/src/components/ui/` + the synced Claude Design project (kept
current by the `design-sync-check` / `design-capture-screen` skills). This part names
tokens/components and says **how to use them**. *(We deliberately keep `name — intent —
boundary`, not the inline-hex pattern most design.md/DESIGN.md guides recommend: we already have
a single source of truth for values — `index.css`, enforced by Tailwind v4 `@theme` — so
repeating hex here would only create drift. The trade-off: this file alone can't be handed to a
tool that has never seen the codebase — it assumes `index.css` is in context too.)*

## 7. Principles
1. **Clarity at scale over decoration** — remove ornament, not information.
2. **One primary action per screen/section** — everything else is secondary.
3. **State is first-class** — health/freshness/change-status always visible, always the same way (StatusBadge, §10).
4. **Semantic, never literal** — style via semantic tokens & existing components, never raw hex or hand-built elements, so light/dark & rebrands "just work".
5. **Speak the family's language** — git-native, source-of-truth vocabulary (§11).

## 8. Color — role · use · boundary  (values → `index.css`)
Use the **semantic token name**, never a raw value. Meet WCAG AA (4.5:1 text, 3:1 UI).

| Token `--color-*` | Use for | Boundary — never |
|---|---|---|
| `background` / `foreground` | app canvas / default text | — |
| `surface` | raised neutral: sidebar, empty-state tiles | primary CTAs |
| `card` | card / popover surface | page background |
| `primary` | **the** primary action (**one per view**), active nav | decoration, large fills |
| `secondary` | quiet action / neutral chip | primary actions |
| `muted(-foreground)` | descriptions, metadata, placeholders | primary text |
| `accent` | hover / selected wash | text, standalone fills |
| `border` / `input` | 1px hairlines, field outlines | fills |
| `ring` | `focus-visible` ring only | anything else |
| `success` / `warning` / `destructive` | status, outcomes, destructive actions | brand/accent, decoration |

Status = tinted bg (`/10`) + soft border (`/30`) + solid dot — **never colour alone**. Brand
accent shifts by theme (light `primary` ≈ near-black; dark `primary` ≈ indigo) — exact values
in `index.css`, not restated here (per §12).

> **⚠️ TODO (brand, owner decision — not Claude's to make):** confirmed via opsmill.com —
> OpsMill/Infrahub's house identity is **turquoise/cyan** (checkmarks, the "Otto" otter mascot
> in teal/blue) on clean neutrals; Styrmin currently uses cool slate + indigo, with no Otto
> anywhere in the frontend yet (`EmptyState.tsx` has no mascot today — §11's mention of Otto is
> aspirational, not implemented). Align to the family, or intentionally stay distinct as the
> "ops layer" sibling? Either is defensible — Styrmin is infra tooling, not the product surface —
> but it should be a stated decision, not a default. Whatever's picked, the value stays in
> `index.css`.

## 9. Typography, spacing, shape  (patterns → source)
- **Font:** Inter (system fallback), mono for code/paths. `TODO`: ship Inter as a web-font — today relies on locally-installed Inter, so the design-sync bundle falls back to system. (Low-risk, mechanical fix whenever someone picks it up — self-hosting a `woff2` subset is a one-PR change, not a design decision.)
- **Type by purpose** (classes live in components): page title `text-2xl font-semibold tracking-tight` (one per page); section/card title `font-semibold`; body/description `text-sm text-muted-foreground`; dense chrome `text-xs`/`text-[13px]`. **Rules:** ≤2 weights per screen · `tracking-tight` on headings · **sentence case, never ALL-CAPS**. Dense chrome type is for metadata/nav only — never body copy.
- **Density is the aesthetic:** tight chrome (`h-12` topbar, `h-8`/`h-9` controls), breathing content (`p-6` cards, `container mx-auto px-6 py-6`). Layout: `AppShell` (sidebar + slim topbar) → `PageLayout` (breadcrumb rooted at "Styrmin" → title + actions → content).
- **Shape/elevation/motion:** single `--radius` base — `rounded-md` (button/badge/input), `rounded-lg` (card/nav). Structure carries on **1px border + surface/card layering**, not shadows (`shadow-sm` ceiling). Subtle fades only; no decorative motion. Never mix sharp + rounded corners in one view.

## 10. Components — usage & decision rules  (APIs → source/catalog)
Import primitives **only** from `@/components/ui/` (never `@base-ui/react` directly). Compose
from existing components; **never hand-build a lookalike**. 16 user-facing primitives (in
`frontend/src/components/ui/`, plus a `slot` `asChild` utility that isn't a component): Alert,
Badge, Button, Card, Checkbox, Collapsible, Dialog, DropdownMenu, Input, Label, Select,
Separator, Skeleton, Tabs, Toast(er), Tooltip.

**Decision criteria (when to use which):**
- **Status/health →** always `StatusBadge`/`getStatusColor` (the single source of truth), never a hand-coloured Badge.
- **Async boundary →** the state trio: `LoadingState` (skeletons) · `EmptyState` · `ErrorState`. Don't roll your own.
- **Card vs. plain row:** Card for a self-contained entity with its own actions; a bordered row/list item for scannable collections — don't give every list item card weight + shadow.
- **Dialog vs. inline:** Dialog only for a focused, interrupting decision; prefer inline/drawer for routine edits.
- **Primary action →** exactly one `Button variant="default"` per view; secondary/ghost for the rest.

Also: reach for app compositions before inventing (`AppShell`, `PageLayout`,
`AutoRefreshIndicator`, `ThemeToggle`, `ConfirmDialog`, `HeaderUserMenu` — all verified to exist
under `frontend/src/components/`). Render every applicable state (hover/focus-visible/disabled/
loading/empty/error). Base UI convention: `data-[open]`/`data-[checked]`/`data-[panel-open]`
(not Radix-era `data-[state=open]`, of which there are zero in the codebase) — see
[`dev/knowledge/frontend/ui-primitives.md`](dev/knowledge/frontend/ui-primitives.md) for the
one documented consumer-side exception.

## 11. Voice & accessibility
- **Voice:** technical, precise, problem-first, engineer-respecting; confident, plainspoken, **not cutesy** in chrome (personality lives in empty states / the Otto mascot, sparingly — see brand TODO in §8; not yet implemented). Buttons = verb+noun; errors = cause + fix. Use canonical domain terms verbatim ([`CONTEXT.md`](CONTEXT.md)): *application driver* (not bare "driver" on first use), cluster, environment, deployment, instance, reconciliation, backup storage location; avoid banned synonyms ("namespace", "k8s cluster", "web app"). Use the git-native lexicon (source of truth, validation, audit, rollback, recorded intent) where it fits — this is also how the sibling Infrahub product talks about itself.
- **Accessibility (non-negotiable):** WCAG AA · visible `focus-visible` ring on every interactive · full keyboard nav · labels/ARIA (Base UI wires these — don't strip) · adequate targets · respect reduced-motion.

## 12. Do / Don't
**Do:** style through semantic tokens & existing components (light/dark falls out free) · one primary action per view · status via StatusBadge · match the dense, bordered, low-shadow dashboard feel · give async views the state trio.
**Don't:**
- ❌ Invent hex / spacing values — tokens only (and don't reproduce values in this doc).
- ❌ Import `@base-ui/react` directly, or rebuild a primitive by hand.
- ❌ Put two primary buttons in one view.
- ❌ Use ALL-CAPS headers.
- ❌ Use gradients, or drop shadows on cards — structure is borders + surface layering.
- ❌ Mix sharp + rounded corners in one view.
- ❌ Signal status/errors by colour alone — always colour **+ text/dot**.
- ❌ Hand-colour a status instead of using StatusBadge.
- ❌ Use `data-[state=open]` (Radix-era) — this is Base UI: `data-[open]`.

---

## 13. Relationship to existing documents & enforcement
```text
Styrmin — Design (this doc)   ← why/goals/scope (Part A) + UI design language (Part B)
   ├── dev/constitution.md    ← non-negotiable principles (wins on principle disagreements)
   ├── dev/knowledge/         ← current-state architecture (wins on current-state facts)
   ├── dev/adr/               ← one decision + rationale (incl. alternatives considered) each
   ├── CONTEXT.md             ← canonical vocabulary
   ├── frontend/src/index.css ← token VALUES (source of truth for Part B) + Tailwind @theme enforcement
   ├── frontend/src/components/ui/ + Claude Design project ← component source/catalog
   └── docs/                  ← user-facing docs
```
**Precedence:** current-state fact → `architecture.md`; principle → constitution; token/component value → the code. This doc is the "why" and "how it should look/feel", not the authority on values.

**Three enforcement layers (rules → framework → eyes):** (1) this doc = the rules; (2)
**Tailwind v4 `@theme`** = the hard guardrail — utilities resolve only to real tokens, so
prompt drift can't invent off-token values (this is the "compile tokens into the framework"
practice, which Styrmin already satisfies); (3) **visual verification** — run the dev server
(vite :5173), drive/screenshot the changed screen with Playwright, compare to the design, list
& fix. (There is no Storybook in this repo, so verification is screen-level via the dev
server; see [`frontend/AGENTS.md`](frontend/AGENTS.md) for the frontend tooling/conventions.)

Per-feature decisions live in that feature's spec; build playbooks live in the
[`design-implement-handoff`](.agents/skills/design-implement-handoff/SKILL.md) skill (turns a
Claude Design handoff bundle into verified code) — not here.

## 14. Open questions (resolve before leaving draft)
1. **Brand accent** — Infrahub turquoise/cyan + Otto mascot, or keep slate/indigo? (§8) Facts
   confirmed against opsmill.com this pass; the call itself is a product/brand decision, left
   for the owner.
2. **Ship Inter as a web-font?** (§9) — mechanical, low-risk; no blocker to doing it whenever convenient.
3. **Stale source — CONFIRMED this pass:** root `CLAUDE.md`'s "Recent Changes"/tech-context
   entries say "Radix UI" / "urql" in multiple places; the app is actually **Base UI + TanStack
   Query** (migrated per `specs/archive/001-base-ui-migration` and the TanStack Query migration spec).
   This is a live Constitution §VII documentation-accuracy violation, not just a hypothetical —
   fix at source in the same change that next touches `CLAUDE.md`.
4. **Home & wiring — RESOLVED this pass:** keep this file at the **project root** as `design.md`
   (matches where `AGENTS.md`/`CLAUDE.md`/`CONTEXT.md`/`README.md` already live, and matches the
   general design.md/DESIGN.md convention of sitting next to the README). Attaching **Part B**
   as a context document ahead of UI prompts is already meaningfully supported: Claude Design
   sync (`design-sync-check`, `design-capture-screen`) and handoff implementation
   (`design-implement-handoff`) already exist as skills in `.agents/skills/` and are in active
   use (see `docs/handoffs/environments-page/`). No actual `DESIGN.md` naming collision was
   found anywhere in the repo during this pass — if a colleague's architecture doc by that name
   exists outside the repo or is still unmerged, confirm directly with them before finalizing.
5. **Owner** — still unassigned; an unowned design doc drifts (Constitution §VII). Highest-priority open item — assign before the next merge that touches this file.
6. **Part A vs. a standalone architecture doc** — moot in practice: `dev/knowledge/architecture.md` already exists and is comprehensive, so Part A is correctly already just a thin pointer to it. No action needed beyond continuing to prune Part A if it ever grows past a summary.

---
<sub>Structure & practices synthesized from (re-verified July 2026): Google design-doc practice — context/scope, goals/non-goals, alternatives-considered, cross-cutting concerns, "short enough to be read" (Malte Ubl, *Design Docs at Google*, industrialempathy.com) — and arc42 (goals, constraints, cross-cutting concepts); the design.md/DESIGN.md-for-AI-agents convention — root-level placement next to README, ~2–3k token budget, structured tokens as hard constraints + prose for judgment calls, negative rules ("don't") alongside positive ones, compile-tokens-into-the-framework enforcement (UX Planet/Babich; Better Stack Community, *DESIGN.md: A Markdown Design System File for AI Coding Agents*; designmd.app; awesome-design-md). Ecosystem/brand facts (turquoise/cyan identity, Otto mascot, docs structure, voice) checked directly against opsmill.com and docs.infrahub.app. Repo facts (constitution principles, architecture shape, ADR-039 non-goal, CONTEXT.md vocabulary, `index.css` token values, `components/ui/` inventory, app compositions, Base UI data-attribute convention, Claude Design skills) checked directly against the Styrmin repository, not assumed. Values & system detail are referenced, never duplicated.</sub>
