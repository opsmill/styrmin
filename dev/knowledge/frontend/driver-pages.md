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

## Load warnings (`LoadDriverDrawer.tsx`)

When a load returns `loadWarnings`, the drawer shows a notification of type `warning` with
`timeout: 0`. It lists one warning per line and stays on screen until the user closes it, because
Styrmin does not store the warnings. A load without warnings shows a `success` notification that
closes on its own.

## Attributes for E2E tests

| Element | Attributes |
|---------|------------|
| Logo | `data-testid="driver-logo"`, `data-logo-state` (`loading`, `image` or `fallback`) |
| Description | `data-testid="driver-description"` (list group header and detail page) |
| Links list | `data-testid="driver-links"`; each host as `data-testid="driver-link-host"` |
| Driver group | `data-testid="driver-group"`, `data-driver-name` |

`backend/tests/e2e/test_ui_smoke.py::test_driver_logo_description_and_links_render` reads these
attributes. See [e2e-testing.md](../backend/e2e-testing.md#serving-external-urls-to-the-ui-browser)
for how it serves the logo without internet access.

## Tests

Vitest tests live in `frontend/src/__tests__/drivers/` (`DriverLogo.test.tsx`,
`DriverListPage.test.tsx`, `driverList.test.ts`, `LoadDriverDrawer.test.tsx`) and
`frontend/src/__tests__/driver-detail/DriverDetailPage.test.tsx`.

## Key Files

| File | Purpose |
|------|---------|
| [frontend/src/pages/drivers/DriverLogo.tsx](../../../frontend/src/pages/drivers/DriverLogo.tsx) | Logo of one driver version and its three states |
| [frontend/src/pages/drivers/DriverListPage.tsx](../../../frontend/src/pages/drivers/DriverListPage.tsx) | Driver list: group headers and flat rows |
| [frontend/src/pages/drivers/DriverDetailPage.tsx](../../../frontend/src/pages/drivers/DriverDetailPage.tsx) | Driver detail: header logo, description, links |
| [frontend/src/pages/drivers/lib/driverList.ts](../../../frontend/src/pages/drivers/lib/driverList.ts) | Filter and latest-version helpers |
| [frontend/src/pages/drivers/LoadDriverDrawer.tsx](../../../frontend/src/pages/drivers/LoadDriverDrawer.tsx) | Load driver drawer and the load-warning notification |
| [frontend/src/components/ClampedText.tsx](../../../frontend/src/components/ClampedText.tsx) | Clamped description with "Show more" |
