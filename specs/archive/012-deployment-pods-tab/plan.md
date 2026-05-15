# Implementation Plan — Pods Tab on Deployment Detail Page

**Status:** Extracted
**PRD:** https://github.com/opsmill/styrmin/issues/204#issuecomment-4412816851
**Design:** Paper artboard "Pods Tab — Option A (Grouped Sections)" in `Styrmin Design Apr 6th`
**Direction:** Option A — grouped sections with inline expand (chosen over Option B single-table and Option C master-detail; see PRD User Stories 4–5 for why drift-as-its-own-section makes A the natural fit)
**Constraint:** ADR-014 ("Pod-status records reflect observed state, not declared state") — `dev/adr/adr-014-pod-status-records-observed-state-not-declared-state.md`

---

## 0. Pre-flight summary (what's already there)

A recon pass confirmed the PRD's claim that the backend is ready and frontend infra is in place. Nothing to build server-side:

- `PodStatus` DB model — `backend/styrmin_backend/db/models.py:557-577`
- `PodStatus` GraphQL type — `backend/styrmin_backend/api/definitions/pod_status/model.py:15-52`
- Standalone `podStatuses(deploymentId: UUID)` query — `backend/styrmin_backend/api/schema/query.py:365-380`. This is what we'll use, **not** the `Deployment.podStatuses` nested field (per PRD §Implementation Decisions).

Frontend patterns also already exist:

- TanStack Query v5 codegen, `useGetDeploymentQuery`-style hooks
- `refetchInterval: autoRefreshEnabled ? 10_000 : false` already used in `DeploymentDetailPage.tsx:69,76,966` — same shape we'll reuse
- `Tabs` / `TabPanel` primitives at `frontend/src/components/ui/tabs.tsx` (custom, not Radix)
- `StatusBadge` exists at `frontend/src/components/StatusBadge.tsx` (we'll likely add phase variants here rather than create a new badge component — verify scope at Phase 2)

What does **not** exist and will be created:

- A clipboard hook (no `navigator.clipboard.writeText` wrapper anywhere in the frontend)
- `GetDeploymentPods.graphql`
- All Pods tab components and the four pure utility functions

---

## 1. Module decomposition & file paths

All paths absolute from repo root.

### New files

| Path | Purpose |
|---|---|
| `frontend/src/graphql/get_deployment_pods.graphql` | Dedicated query (PRD §Implementation Decisions/GraphQL) |
| `frontend/src/pages/deployments/PodsTab/index.tsx` | Re-export of `PodsTab` |
| `frontend/src/pages/deployments/PodsTab/PodsTab.tsx` | Orchestrator: query + loading/empty/error + section rendering |
| `frontend/src/pages/deployments/PodsTab/PodsTab.test.tsx` | Empty-state cases (no pods + non-RUNNING, no pods + RUNNING) |
| `frontend/src/pages/deployments/PodsTab/PodSection.tsx` | Single section card (declared / drift / unlabeled variants) |
| `frontend/src/pages/deployments/PodsTab/PodRow.tsx` | Collapsed row + inline expanded panel (containers + commands) |
| `frontend/src/pages/deployments/PodsTab/PodRow.test.tsx` | Expansion toggle, stale indicator, copy writes expected string |
| `frontend/src/pages/deployments/PodsTab/KubectlCommands.tsx` | Collapsible Commands section with 4 rows + Copy buttons |
| `frontend/src/pages/deployments/PodsTab/AutoRefreshChip.tsx` | "● Auto-refresh · 10s · last Xs ago" chip in tab header |
| `frontend/src/pages/deployments/PodsTab/groupPodsByComponent.ts` | Pure: `(podStatuses, declaredComponents) → { declared, drifting, unlabeled }` |
| `frontend/src/pages/deployments/PodsTab/groupPodsByComponent.test.ts` | Drift / declared-empty / multi-drift cases |
| `frontend/src/pages/deployments/PodsTab/parseContainerState.ts` | Pure: agent state string → `{ state, reason }` |
| `frontend/src/pages/deployments/PodsTab/parseContainerState.test.ts` | running / waiting:* / terminated:* / unknown / malformed |
| `frontend/src/pages/deployments/PodsTab/classifyStaleness.ts` | Pure: `(lastPolledAt, now) → "fresh" \| "stale" \| "not_reporting"` |
| `frontend/src/pages/deployments/PodsTab/classifyStaleness.test.ts` | Boundary at 30s and 2min |
| `frontend/src/pages/deployments/PodsTab/buildKubectlCommand.ts` | Pure: `(kind, namespace, podName) → string`. Single source for all 4 templates. |
| `frontend/src/pages/deployments/PodsTab/buildKubectlCommand.test.ts` | All 4 templates verified |
| `frontend/src/hooks/useCopyToClipboard.ts` | New shared hook — `navigator.clipboard.writeText` + 2s "Copied" toggle |
| `backend/tests/e2e/pages/pods_tab.py` | Page object: `goto`, `read_pod_rows`, `expand_pod`, `copy_logs_command` |
| `backend/tests/e2e/test_deployment_pods_tab.py` | One happy-path UI scenario (PRD §Testing/E2E) |

### Modified files

| Path | Change |
|---|---|
| `frontend/src/pages/deployments/DeploymentDetailPage.tsx` | (a) Add `{ id: "pods", label: "Pods" }` to `DEPLOYMENT_TABS` (lines 50–55). (b) Mount `<TabPanel active={activeTab === "pods"}><PodsTab deploymentId={deployment.id} isActive={activeTab === "pods"} declaredComponents={deployment.driver.components} /></TabPanel>`. (c) **No other changes** — explicitly avoid absorbing logic into this file (PRD module-decomposition note). |
| `frontend/src/components/StatusBadge.tsx` *(only if it doesn't already have phase variants)* | Add `RUNNING / PENDING / SUCCEEDED / FAILED / UNKNOWN` styling variants if missing. Re-check at Phase 2 — recon noted the file exists but did not enumerate variants. |

The deployment detail file gains ~8 lines. That's it for modifications.

---

## 2. GraphQL query

`frontend/src/graphql/get_deployment_pods.graphql`:

```graphql
query GetDeploymentPods($deploymentId: UUID!) {
  podStatuses(deploymentId: $deploymentId) {
    id
    podName
    namespace
    phase
    ready
    restartCount
    nodeName
    componentName
    startedAt
    createdOn
    lastPolledAt
    containerStatuses {
      name
      image
      ready
      restartCount
      state         # flattened string per ADR-014
    }
  }
}
```

Field names must match the existing Strawberry type at `backend/styrmin_backend/api/definitions/pod_status/model.py` — verify camelCase mapping during implementation. After creation, run:

```bash
uv run invoke validate-graphql
uv run invoke generate
```

Generated hook usage:

```ts
useGetDeploymentPodsQuery(
  { deploymentId },
  { refetchInterval: isActive ? 10_000 : false, enabled: isActive },
)
```

---

## 3. Phases & sequencing

### Phase 1 — Pure functions + GraphQL (no UI) · ~½ day

Build the four pure functions and their tests first; build the query and confirm codegen produces the expected hook.

1. `get_deployment_pods.graphql` → `uv run invoke validate-graphql` → `uv run invoke generate`
2. `groupPodsByComponent.ts` + test — input shape uses the generated `PodStatus` type
3. `parseContainerState.ts` + test
4. `classifyStaleness.ts` + test — takes `(lastPolledAt: string, now: Date)` so tests can inject `now`
5. `buildKubectlCommand.ts` + test — kind: `"logs" | "describe" | "events" | "exec"`, returns the exact PRD-specified string for each

**Gate:** all pure-function tests green before touching any TSX.

### Phase 2 — Leaf components · ~½ day

6. `useCopyToClipboard` hook (no test — covered indirectly by PodRow.test.tsx assertion that clipboard receives the expected string)
7. `KubectlCommands.tsx` — receives `(namespace, podName)`, uses `buildKubectlCommand` for each line, collapsed by default
8. `AutoRefreshChip.tsx` — pure presentation, takes `dataUpdatedAt` from the TanStack Query result

### Phase 3 — Composite components · ~½ day

9. `PodRow.tsx` — internal `useState<boolean>` for expansion, renders collapsed row + expanded panel (containers card + `<KubectlCommands>`). Uses `classifyStaleness` for the inline stale tag and `parseContainerState` for container detail.
10. `PodRow.test.tsx` — three assertions:
    a. clicking row toggles expansion
    b. stale tag renders when `lastPolledAt` > 30s
    c. clicking Copy on logs writes the expected `kubectl logs ...` string to a mocked clipboard
11. `PodSection.tsx` — header band + column header row + children rows; three visual variants (declared / drifting yellow chrome / unlabeled). Empty declared variant renders dashed-circle placeholder.

### Phase 4 — Orchestrator & wire-up · ~½ day

12. `PodsTab.tsx`:
    - `useGetDeploymentPodsQuery({ deploymentId }, { refetchInterval: isActive ? 10_000 : false, enabled: isActive })`
    - Loading state, error state, empty states (User Stories 17–18: differentiate by `deployment.phase`)
    - Calls `groupPodsByComponent(data.podStatuses, declaredComponents)` and maps the three buckets to `<PodSection>` instances
    - Renders `<AutoRefreshChip dataUpdatedAt={query.dataUpdatedAt} />` in the tab header
13. `PodsTab.test.tsx` — empty-state cases
14. Modify `DeploymentDetailPage.tsx` per §1 table. Manually verify in the running dev server that the tab appears and refresh-pauses-when-inactive works (open Pods tab, check Network tab refreshes every 10s; switch to Overview, confirm refreshes stop).

### Phase 5 — E2E + docs · ~½ day

15. `backend/tests/e2e/pages/pods_tab.py` — page object with at minimum: `goto_pods_tab()`, `wait_for_pod_row(component, name)`, `expand_pod(name)`, `copy_logs_command(name)`, `read_clipboard()`.
16. `backend/tests/e2e/test_deployment_pods_tab.py` — the single PRD-specified happy-path scenario, marked:
    ```python
    @pytest.mark.ci
    @pytest.mark.ui_only(
        reason="Pods tab UI flow — SDK exposes podStatuses already and is covered by "
        "service-layer tests; api variant would only re-run the SDK call.",
    )
    ```
17. Run the test with the project's standard recipe: `sleep infinity | uv run pytest backend/tests/e2e/test_deployment_pods_tab.py -v -s --pdb`.

### Phase 6 — Polish & merge · ~½ day

18. Run `uv run invoke format lint`, `cd frontend && pnpm test`, ensure pre-commit hooks pass.
19. Visual QA against the Paper artboard at 1440px — focus on the four review checklist points the design enforces (spacing, type hierarchy, column alignment, contrast for muted text).
20. Update `CLAUDE.md` "Active Technologies" / "Recent Changes" footer entry: e.g. `Added Pods tab to deployment detail (PRD #204)`.

**Total:** ~3 days of focused work.

---

## 4. Test plan summary

Mapping directly to PRD §Testing:

| Behavior | Test type | File |
|---|---|---|
| Bucket split | unit | `groupPodsByComponent.test.ts` |
| Container state parsing (incl. malformed) | unit | `parseContainerState.test.ts` |
| Staleness thresholds (30s / 2min boundaries) | unit | `classifyStaleness.test.ts` |
| All 4 kubectl template strings | unit | `buildKubectlCommand.test.ts` |
| Row expansion, stale tag rendering, clipboard write | component | `PodRow.test.tsx` |
| Empty states (RUNNING vs non-RUNNING) | component | `PodsTab.test.tsx` |
| One happy-path UI flow (RUNNING pod → expand → Copy logs → verify clipboard) | E2E | `test_deployment_pods_tab.py` |

Time mocking for the staleness test uses Vitest's `vi.useFakeTimers()` / `vi.setSystemTime()` — already in use elsewhere in the frontend test suite.

---

## 5. Visual contract (from the Paper artboard)

So the implementer hits the design without ambiguity:

- Card: `border: 1px solid #E5E7EB; border-radius: 12px; background: #FFFFFF;`
- Section header band: `background: #FAFAFA; padding: 14px 20px;` — except drift sections where `background: #FFFBEB; border: 1px solid #FCD34D;`
- Phase badge colours:
  - RUNNING `#10B981` dot on `#ECFDF5` ground, text `#047857`
  - PENDING `#F59E0B` on `#FEF3C7`, text `#92400E`
  - SUCCEEDED `#3B82F6` on `#DBEAFE`, text `#1E40AF`
  - FAILED on `#FEE2E2` (text `#991B1B`)
  - UNKNOWN gray
- Restart count: plain text for 0, `#FEF3C7`/`#92400E` pill for 1–4, `#FEE2E2`/`#991B1B` for ≥5
- Stale tag rendered inline next to pod name in collapsed row (matches PRD User Story 11)
- Column widths in the row: pod name `flex:1`, phase 110px, ready 64px right-aligned, restarts 96px right-aligned with `padding-right:16px`, node 156px, age 80px right-aligned, expand-arrow 20px slot — these specific widths fix the "RESTARTSNODE" collision spotted during mock review
- Fonts: Inter for UI, JetBrains Mono 13px for pod names / namespace / image references / kubectl command text

---

## 6. Open questions / decisions worth confirming before implementation

1. **Auto-refresh chip behavior.** The mock shows "● Auto-refresh · 10s · last 3s ago" — purely informational. Should it also be a toggle (pause/resume the polling)? PRD doesn't specify. **Default plan:** informational only.
2. **`StatusBadge` reuse vs new `PhaseBadge`.** If the existing `StatusBadge` already covers RUNNING/PENDING/SUCCEEDED/FAILED visually, reuse it. If it's deployment-phase-specific (different vocabulary), add a small `PhaseBadge` next to it rather than overload one component. **Default plan:** reuse if vocabulary matches, otherwise create `PhaseBadge`.
3. **Empty-state Timeline link.** PRD User Story 18 says "points me at the Timeline tab to investigate agent reachability". **Default plan:** a button labeled "Open Timeline" that calls `setActiveTab("timeline")`.
4. **`(observed since)` tooltip for `created_on` fallback.** PRD says use `started_at` primary, `created_on` fallback with tooltip. Recon did not surface a tooltip primitive in the codebase. **Default plan:** use a minimal `title="..."` HTML attribute rather than build a new component.

---

## 7. Out of scope (from PRD §Out of Scope)

- Streaming live logs inside the UI
- Editing, restarting, or deleting pods from the UI
- Showing historical pod records from previous deployment revisions
- Capturing prior termination reasons (`lastState.terminated.{reason,exitCode,finishedAt}`) — separate follow-up issue
- URL persistence for the active tab — separate cross-tab change
