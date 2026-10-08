# UI Contract: Driver Logo, Description and Links

Selectors and attributes that tests (Vitest and the E2E page objects) rely on.

## `DriverLogo` component

`frontend/src/pages/drivers/DriverLogo.tsx`

Props: `icon: string | null | undefined`, `driverName: string`, `size?: "sm" | "md"` (`sm` = 20 px frame for flat rows, `md` = 32 px frame for headers).

| State | DOM |
|-------|-----|
| `icon` set, not failed | `<span data-testid="driver-logo" data-logo-state="image"><img src={icon} alt="{driverName} logo" referrerpolicy="no-referrer" loading="lazy" decoding="async" class="object-contain"></span>` |
| `icon` null/empty, or `<img>` fired `error` | `<span data-testid="driver-logo" data-logo-state="fallback">` with the lucide `Package` icon (`aria-hidden`) |

- The frame size and border are the same in both states, so the layout does not change.
- When `icon` changes, the component starts again in the `image` state.

## Driver list page (`/drivers`)

- Group header (grouped view), one per driver:
  - Contains `[data-testid=driver-logo]` for the latest-wins version.
  - Has `data-testid="driver-group"` and `data-driver-name="<name>"` on the group root.
  - Description element `[data-testid=driver-description]` with `title` = full text and one-line truncation. It is absent when there is no description.
- Flat view row: `[data-testid=driver-logo]` (size `sm`) before the driver name, for the row's version.

## Driver detail page (`/drivers/$driverId`)

- `PageLayout` header: `[data-testid=driver-logo]` (size `md`) before the `<h1>`, for the selected version.
- Description: `[data-testid=driver-description]`, plain text, `whitespace-pre-line`, between the version row and the tabs. Absent when not set.
- Overview tab: `[data-testid=driver-links]` list. Each item is an `<a href={url} target="_blank" rel="noopener noreferrer">{label}</a>`. Absent when there are no links.

## E2E page-object additions

`backend/tests/e2e/pages/drivers_list.py` (`DriversListPage`) gains read helpers used by `test_ui_smoke.py`:

- `driver_group_logo(driver_name) -> Locator` — the `[data-testid=driver-logo]` inside `[data-testid=driver-group][data-driver-name=<name>]`.

The detail assertions in `test_ui_smoke.py` use locators inline, as `test_driver_detail_inspects_versions_via_tabs` already does.
