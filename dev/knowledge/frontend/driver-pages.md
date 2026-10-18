<!-- Extracted from specs/020-driver-info-display on 2026-10-13 -->

# Driver Pages

## Overview

The driver list page and the driver detail page show the logo, the description and the links
that a driver author sets in `spec.info` of the driver specification file. Styrmin stores these
values on each application driver version, so two versions of one driver can show different
values. The browser of each viewer loads the logo from the URL in the file; Styrmin does not
fetch, proxy or store the image.

Design rationale: [ADR-067](../../adr/0067-driver-logos-loaded-by-the-viewer-browser.md) (logos)
and [ADR-068](../../adr/0068-invalid-driver-info-dropped-with-load-warning.md) (invalid values and
load warnings). GraphQL fields: [api.md](../backend/api.md).

## File layout

```text
frontend/src/
├── pages/drivers/
│   ├── DriverListPage.tsx          # Grouped view and flat list of driver versions
│   ├── DriverDetailPage.tsx        # One driver: version selector, description, Overview tab
│   ├── DriverLogo.tsx              # Logo of one driver version, with the generic icon as fallback
│   ├── LoadDriverDrawer.tsx        # Load driver drawer; shows the load warnings
│   └── lib/driverList.ts           # Filter, latest version and grouping helpers
├── components/
│   ├── ClampedText.tsx             # Text cut to 1 or 3 lines, with "Show more"
│   └── PageLayout.tsx              # Page header with the optional `icon` slot
└── graphql/
    ├── list_drivers.graphql        # Versions with `icon` and `description`
    ├── get_driver.graphql          # Versions with `icon`, `description` and `links`
    ├── load_remote_driver.graphql  # Returns `loadWarnings`
    └── load_local_driver.graphql   # Returns `loadWarnings`
```

## Driver logo (`DriverLogo.tsx`)

The three places that show a driver logo (the list group header, the flat list row and the detail
page header) use `DriverLogo`. It takes the `icon` URL of one driver version and has three states,
which it writes to `data-logo-state`:

- `loading`: the image is downloading. The generic package icon shows, and the image stays
  hidden until it has loaded.
- `image`: the image has loaded. It shows on a white tile, so dark logos stay visible in the dark
  theme.
- `fallback`: the version has no logo, or the image failed to load. The generic package icon
  shows, and no `<img>` element is rendered.

Details of the image element and the component:

- The image is an `<img>` with `alt=""`, `referrerPolicy="no-referrer"` and `decoding="async"`.
  The logo host therefore does not receive the address of the Styrmin page.
- `loading` is `lazy` by default. The detail page header passes `eager`, because that logo is
  always in view.
- The inner frame is keyed by the icon URL, so a new URL starts again in the `loading` state.
- A ref callback sets the `image` state when the browser already has the image in its cache,
  because a cached image can finish loading before React attaches `onLoad`.
- `size="sm"` is a 20-pixel tile (`h-5 w-5`) and `size="md"` a 32-pixel tile (`h-8 w-8`).

The API returns `icon: null` for every driver version when the operator sets
`STYRMIN_DRIVER_SHOW_LOGOS` to `false` (Helm value `styrmin.driver.showLogos`). The pages then show
the generic icon, and the browser requests no logo. The stored URLs are kept.

## Driver list page (`DriverListPage.tsx`)

- Grouped view: each driver group header (`AppGroup`) shows the logo and the description of the
  group's latest version. `filterDrivers` computes `latestVersion` from all loaded versions before
  it applies the filter, so the filter never changes which logo the header shows. The description
  uses `ClampedText` with one line.
- Flat list: each row (`FlatTable`) shows the small logo of its own version, without the
  description.
- The filter matches the driver name, the version string, the source, the supported versions and
  the description (`versionMatches` in `lib/driverList.ts`).

## Driver detail page (`DriverDetailPage.tsx`)

- The header shows the logo of the selected version through the `icon` slot of `PageLayout`,
  which renders it before the title.
- The description of the selected version uses `ClampedText` with three lines and
  `whitespace-pre-line`, so line breaks in the driver file are kept. It is keyed by the version
  id, so choosing another version collapses it again.
- The Overview tab (`OverviewPanel`) shows a "Links" section only when the version has links.
  Each link:
  - opens in a new tab, with `target="_blank"` and `rel="noopener noreferrer"`;
  - has the screen-reader text "(opens in a new tab)" after its label;
  - shows the host it goes to, read with `new URL(url).host`, or the whole URL when it cannot be
    parsed.

## Components tab (`driver-detail/tabs/ComponentsTab.tsx`)

<!-- Extracted from specs/023-per-component-replicas on 2026-10-15 -->

The Components tab of the driver detail page shows one card per component of the selected
version. Besides the identifier labels and the other declared keys, each card has three rows read
from `componentConfigs` in `get_driver.graphql`:

- **Container** (`componentConfigs[].container`), or "None declared".
- **Replicas** (`driver-component-replicas`): the driver default (`componentConfigs[].replicas`),
  or "not set" with a tooltip saying that the chart's count applies unless a deployment overrides
  it.
- **Singleton** (`driver-component-singleton`): "yes" or "no" (`componentConfigs[].singleton`).

`flattenDecl` skips `identifier`, `container`, `replicas` and `singleton` (`OWN_ROW_KEYS`), so the
three values are not listed twice. See
[ADR-070](../../adr/0070-replica-overrides-and-retired-parameters.md).

## Load warnings (`LoadDriverDrawer.tsx`)

When a load returns `loadWarnings`, the drawer shows a notification of type `warning` with
`timeout: 0`. It lists one warning per line and stays on screen until the user closes it, because
Styrmin does not store the warnings. A load without warnings shows a `success` notification that
closes on its own.

## Driver directory

<!-- Extracted from specs/028-git-driver-directory on 2026-10-18 -->

A git driver version can be loaded from a driver directory, a folder of the repository relative to its root (spec 028). Every page reads the computed GraphQL field `driverDirectory`, which is `null` for a load from the repository root and for a local driver version. No page reads `sourceType` and `sourcePath` to decide this.

- **Load drawer** (`LoadDriverDrawer.tsx`), git tab:
  - The third field is "Driver directory (optional)" (`id="driverDirectory"`). Its help text is linked with `aria-describedby`. The drawer sends the trimmed value only when it is not empty, so an empty field loads from the repository root. The drawer does not check the value: the server applies the rules, so all load surfaces share one rule.
  - A server error whose message starts with "Driver directory " shows under the field, with `aria-invalid`. Other errors show in the alert at the top. The form keeps the values the admin entered.
  - The form refuses a repository URL that is a GitHub `/tree/` or `/blob/` link, or a GitLab `/-/tree/` or `/-/blob/` link, before any request. The message gives the repository URL to enter (`repositoryOfFolderLink` in `lib/repositoryUrl.ts`).
  - While a git load runs, the submit button reads "Cloning repository…".
- **Overview tab**: a "Driver directory" row follows the "Source" row when `driverDirectory` is set. Its copy button is named "Copy driver directory". There is no row for a load from the repository root.
- **Drivers list**: the Source cell shows `<repository> @ <branch> · <driver directory>` (`versionSource` in `lib/driverList.ts`). The list filter matches the same text, so searching for a driver directory finds its versions.
- **Version pickers**: the version switcher of the driver detail page, the deploy form and the upgrade dialog end each label with ` · <driver directory>` (`withDriverDirectory` in `lib/driverVersion.ts`). Two drivers with the same name and commit in one repository therefore have different labels. The version switcher's search matches the driver directory.
- **Upgrade dialog** (`DeploymentDetailPage.tsx`): the latest-wins rule ignores the driver directory, so "Latest (auto)" can move a deployment to a driver version from another driver directory. While "Latest (auto)" is selected and the driver's versions come from more than one driver directory (the repository root counts as one), `DriverDirectoryChangeNotice` warns about this and tells the admin to pick a version to stay in the current driver directory (`driverDirectoriesOf` in `lib/driverVersion.ts`). The frontend cannot evaluate the PEP 440 ranges, so the notice says that the move can happen, not that it will.

## Attributes for E2E tests

| Element | Attributes |
|---------|------------|
| Logo | `data-testid="driver-logo"`, `data-logo-state` (`loading`, `image` or `fallback`) |
| Description | `data-testid="driver-description"` (list group header and detail page) |
| Links list | `data-testid="driver-links"`; each host as `data-testid="driver-link-host"` |
| Driver group | `data-testid="driver-group"`, `data-driver-name` |
| Component replicas and singleton rows | `data-testid="driver-component-replicas"`, `data-testid="driver-component-singleton"` |
| Overview "Driver directory" row | `data-testid="driver-overview-driver-directory"` |
| Driver directory error in the load drawer | `data-testid="driver-directory-error"` |
| Upgrade dialog driver directory warning | `data-testid="driver-directory-change-notice"` |

`backend/tests/e2e/test_ui_smoke.py::test_driver_logo_description_and_links_render` reads these
attributes. See [e2e-testing.md](../backend/e2e-testing.md#serving-external-urls-to-the-ui-browser)
for how it serves the logo without internet access.

## Tests

Vitest tests live in `frontend/src/__tests__/drivers/` (`DriverLogo.test.tsx`,
`DriverListPage.test.tsx`, `driverList.test.ts`, `LoadDriverDrawer.test.tsx`,
`ComponentsTab.test.tsx`, `repositoryUrl.test.ts`) and `frontend/src/__tests__/driver-detail/DriverDetailPage.test.tsx`. The driver directory labels and the upgrade warning are tested in `frontend/src/__tests__/lib/driverVersion.test.ts` and `frontend/src/__tests__/deployment-detail/UpgradeDialogDriverDirectory.test.tsx`.

## Key Files

| File | Purpose |
|------|---------|
| [frontend/src/pages/drivers/DriverLogo.tsx](../../../frontend/src/pages/drivers/DriverLogo.tsx) | Logo of one driver version and its three states |
| [frontend/src/pages/drivers/DriverListPage.tsx](../../../frontend/src/pages/drivers/DriverListPage.tsx) | Driver list: group headers and flat rows |
| [frontend/src/pages/drivers/DriverDetailPage.tsx](../../../frontend/src/pages/drivers/DriverDetailPage.tsx) | Driver detail: header logo, description, links |
| [frontend/src/pages/drivers/lib/driverList.ts](../../../frontend/src/pages/drivers/lib/driverList.ts) | Filter and latest-version helpers |
| [frontend/src/pages/drivers/LoadDriverDrawer.tsx](../../../frontend/src/pages/drivers/LoadDriverDrawer.tsx) | Load driver drawer and the load-warning notification |
| [frontend/src/pages/drivers/lib/repositoryUrl.ts](../../../frontend/src/pages/drivers/lib/repositoryUrl.ts) | Repository URL of a GitHub or GitLab folder or file link, which the load drawer refuses |
| [frontend/src/lib/driverVersion.ts](../../../frontend/src/lib/driverVersion.ts) | Driver version labels, with the driver directory, and the driver directories of a driver's versions |
| [frontend/src/components/deployment/DriverDirectoryChangeNotice.tsx](../../../frontend/src/components/deployment/DriverDirectoryChangeNotice.tsx) | Upgrade dialog warning that "Latest (auto)" can change the driver directory |
| [frontend/src/components/ClampedText.tsx](../../../frontend/src/components/ClampedText.tsx) | Clamped description with "Show more" |
| [frontend/src/pages/drivers/driver-detail/tabs/ComponentsTab.tsx](../../../frontend/src/pages/drivers/driver-detail/tabs/ComponentsTab.tsx) | Components tab: container, replicas and singleton per component |
