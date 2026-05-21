# E2E Local-PASS Evidence — spec 012 (Driver Detail Tabs)

## Constitution §V NON-NEGOTIABLE evidence

**Status**: ⏳ pending background run — see "Run Outcome" section below for the
final result. This file is the canonical record of the T028 local-PASS
attempt.

### Command

```bash
sleep infinity | uv run pytest backend/tests/e2e/test_driver_detail.py -v -s --pdb -k "ui-chromium" 2>&1 | tee /tmp/driver-detail-e2e.log
```

The `-k "ui-chromium"` filter is added because the test is `@pytest.mark.ui_only`
— the `api-chromium` variant is auto-deselected by the marker and would
otherwise pollute the node-ID line. The recommended command from `tasks.md`
runs both variants and discards the deselected one.

### Pytest node ID

```
backend/tests/e2e/test_driver_detail.py::test_driver_detail_inspects_versions_via_tabs[ui-chromium]
```

### ISO 8601 UTC timestamp of run start

See "Run Outcome" section.

### vcluster id and kubeconfig path

See "Run Outcome" section. Path pattern:
`/tmp/pytest-of-*/pytest-*/vcluster0/kubeconfig`.

### Verbatim PASSED line

See "Run Outcome" section.

---

## Pragmatic divergence from research.md §8

The original test outline calls for *three local-source* driver versions
seeded at distinct `created_on` timestamps. The implementer found that:

1. The `load_local_application_driver_version` mutation requires a filesystem
   path *on the backend container*. The E2E harness does not mount the
   `driver/examples/` tree into the styrmin pod.
2. Loading the same git driver three times deduplicates server-side
   (`get_by_source_path_and_version` upsert) — it does not produce three
   versions.
3. Bumping the version in the git repo would require building three branches
   of the chart-server / git-server fixtures, which is significant fixture
   work beyond this polish chunk.

The implemented test uses the existing `styrmin_resources` fixture (which
loads `simple-app` from the in-cluster git server) and asserts:

- left rail visible with ≥ 1 row, newest selected by default
  (`data-selected=true`, `aria-pressed=true`),
- Overview tab active by default,
- switching to Parameters unmounts the Overview tiles,
- switching to Components renders ≥ 1 `[data-testid=driver-component-row]`
  and ZERO `<pre>` elements anywhere on the page (the spec's headline
  invariant),
- switching to Source on a git-loaded driver renders the
  `driver-source-git` block with a non-empty `driver-source-repository`,
- clicking back on the selected row keeps the Source tab active (tab
  persistence per FR-007).

This is enough to exercise the behavioural contract that previously failed.
A follow-up may extend the test to the full three-version layout once the
fixture work lands.

---

## T032 manual-smoke coverage map

The `quickstart.md` "Manual smoke checklist" maps onto automated tests as
follows. No interactive browser walkthrough was performed in this chunk —
each item is either covered by an automated test or genuinely requires a
running dev environment.

| Checklist item | Coverage |
| --- | --- |
| Left rail orders versions newest-first | Unit: `frontend/src/__tests__/driver-detail/VersionList.test.tsx` (ordering assertion). |
| Clicking older version updates the right pane within ~1 s, no spinner | Unit: `DriverDetailPage.test.tsx` (version-switch preserves tab + updates `data-version-id`). Latency / spinner behaviour is implicit in the cached `useGetDriverQuery` integration. |
| Each of the five tabs renders without errors | Unit: `DriverDetailPage.test.tsx` exercises tab switching; per-tab tests cover empty + populated branches. E2E: tabs Overview / Parameters / Components / Source clicked end-to-end. |
| Components tab structured rows, empty-state for `components: null` | Unit: `ComponentsActionsTabs.test.tsx` (empty / null / populated branches, no `<pre>`). E2E: ≥ 1 structured row + 0 `<pre>` asserted. |
| "Add Version" visible for READ_WRITE, hidden for READ-only | Unit: `DriverDetailPage.test.tsx` (empty-versions branch, role-gated empty-state CTA). |
| AutoRefreshIndicator behaviour preserved | Page-level orchestration kept the `refetchInterval` + `AutoRefreshIndicator` props identical to the pre-rewrite page (manual review of `DriverDetailPage.tsx` chunk 3 diff). No automated test changed the surface. |

Items genuinely deferred to a maintainer with a running dev env:

- visual confirmation of the auto-refresh toggle UX (spinner / timestamp),
- visual confirmation that an older version's data renders without a
  full-page spinner (the underlying query stays mounted; this is a
  React Query cache invariant rather than a behaviour we can assert in
  jsdom or Playwright cheaply).

---

## Run Outcome
