# Contract: SDK, CLI and frontend surfaces for the driver directory

**Feature**: [spec.md](../spec.md) | FR-001, FR-005

## SDK — `drivers.load_version`

[`python_sdk/src/styrmin_sdk/resources/drivers.py`](../../../python_sdk/src/styrmin_sdk/resources/drivers.py)

```python
async def load_version(
    self,
    repository_url: str,
    branch: str,
    driver_directory: str | None = None,
) -> LoadRemoteApplicationDriverVersionLoadRemoteApplicationDriverVersion: ...
```

- Sends `driverDirectory` only when `driver_directory` is not `None`.
- `load_version.graphql`:

```graphql
mutation LoadRemoteApplicationDriverVersion(
    $repositoryUrl: String!
    $branch: String!
    $driverDirectory: String = null
) {
    loadRemoteApplicationDriverVersion(
        repositoryUrl: $repositoryUrl
        branch: $branch
        driverDirectory: $driverDirectory
    ) {
        # existing selection, plus:
        sourceRepository
        sourceBranch
        sourcePath
    }
}
```

- Regenerate `_generated/` with `uv run invoke generate`.

## CLI — `styrminctl drivers load-version`

[`cli/src/styrminctl/commands/drivers.py`](../../../cli/src/styrminctl/commands/drivers.py)

```text
styrminctl drivers load-version REPOSITORY_URL BRANCH [--driver-directory PATH]

  --driver-directory PATH  Folder of the repository that holds driver.styrmin.yml,
                           relative to the repository root. Default: the repository root.
```

Output, after the existing `Commit SHA:` line, when the version has a `sourcePath`:

```text
  Driver directory: drivers/infrahub
```

A refused or failed load prints the server's message through the existing error handler, exit code unchanged.

## Frontend — "Load a driver" drawer

[`frontend/src/pages/drivers/LoadDriverDrawer.tsx`](../../../frontend/src/pages/drivers/LoadDriverDrawer.tsx), [`frontend/src/graphql/load_remote_driver.graphql`](../../../frontend/src/graphql/load_remote_driver.graphql)

- Git tab fields, in order: Repository URL, Branch, **Driver directory** (new, `id="driverDirectory"`, optional, placeholder `drivers/my-driver`, help text "Folder that holds driver.styrmin.yml, relative to the repository root. Leave empty for the root.").
- The form schema accepts an empty value. On submit the drawer sends `driverDirectory` only when the trimmed value is not empty.
- A server error shows in the existing error alert; the form keeps the values entered.
- `load_remote_driver.graphql` takes `$driverDirectory: String = null`.

## Frontend — Overview tab of a driver version

[`frontend/src/pages/drivers/DriverDetailPage.tsx`](../../../frontend/src/pages/drivers/DriverDetailPage.tsx), `OverviewPanel`

- For a git driver version with a `sourcePath`, a row **Driver directory** follows the **Source** row, shows the value in monospace and has a copy button, like the Source row.
- No row for a git driver version without `sourcePath`. Local driver versions keep their **Path** row and get no new row.

## Frontend — drivers list Source cell

[`frontend/src/pages/drivers/lib/driverList.ts`](../../../frontend/src/pages/drivers/lib/driverList.ts), `versionSource`

| Version | Source cell |
| --- | --- |
| Local | `<sourcePath>` (unchanged) |
| Git, no `sourcePath` | `<repository> @ <branch>` (unchanged) |
| Git, `sourcePath` set | `<repository> @ <branch> · <sourcePath>` |

The list's search matches the same text, so searching for a driver directory finds its versions.

## E2E page objects and scenario driver

- `ScenarioDriver.load_driver_version(*, git_url, ref, driver_directory=None)` on the protocol, the API driver and the UI driver ([`backend/tests/e2e/drivers/`](../../../backend/tests/e2e/drivers/)).
- `DriversListPage.load_remote_version(..., driver_directory=None)` fills `#driverDirectory` when given ([`pages/drivers_list.py`](../../../backend/tests/e2e/pages/drivers_list.py)).
- The Overview row carries `data-testid="driver-overview-driver-directory"` so the UI test reads it without depending on row order.
