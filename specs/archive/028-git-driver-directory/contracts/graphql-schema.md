# Contract: GraphQL — `loadRemoteApplicationDriverVersion` takes a driver directory

**Feature**: [spec.md](../spec.md) | FR-001, FR-005, FR-007, FR-008, FR-009

## Schema change (`schema.graphql`)

```graphql
type Mutation {
  # before
  loadRemoteApplicationDriverVersion(repositoryUrl: String!, branch: String!): ApplicationDriverVersion

  # after
  loadRemoteApplicationDriverVersion(
    repositoryUrl: String!
    branch: String!
    driverDirectory: String = null
  ): ApplicationDriverVersion
}
```

- Role: `ADMIN`, unchanged.
- `driverDirectory` is optional. `null`, `""`, `"."` and `"./"` load from the repository root, as a call without the argument does.
- No change to `ApplicationDriverVersion`. `sourcePath: String` now returns the stored driver directory for git driver versions loaded from one.

The resolver passes the argument through to `load_application_driver_from_git_repository(..., driver_directory=...)`.

## Behaviour

| Call | Result |
| --- | --- |
| `driverDirectory: "drivers/infrahub"`, folder holds the three files | New driver version, `sourceType: "git"`, `sourcePath: "drivers/infrahub"`, `sourceCommitSha` = commit of the repository |
| Same call again at the same commit, `driverDirectory: "./drivers/infrahub/"` | Same `id` as the first call |
| No `driverDirectory`, repository root holds the three files | `sourcePath: null`; same `id` as an existing root driver version at that commit |
| `driverDirectory: "/etc"`, `"../x"`, `"a/../b"`, `"drivers\\infrahub"` | Error before the clone (see below) |
| Driver directory, or one of the three files, is a symlink whose real path is outside the clone | Error after the clone, no driver version |
| Driver directory missing or not a folder | Error naming driver directory, repository, branch, commit |
| Driver directory without `driver.styrmin.yml` | Error naming driver directory, repository, branch, commit, and the missing file |

## Errors

All errors are GraphQL errors with `extensions.code: "VALIDATION_ERROR"` (existing `DriverError` subclasses). Messages:

| Case | Message (shape) |
| --- | --- |
| Refused value | `Driver directory '<given>' is refused: <rule>. Give a path relative to the repository root, such as 'drivers/infrahub'.` where `<rule>` is `it is an absolute path`, `it contains a '..' segment`, `it contains a backslash` or `it contains a NUL character` |
| Path outside the clone | `Driver directory '<dir>' of repository '<url>' (branch '<branch>', commit <sha>) leads outside the repository: '<relative path>' is a symlink to a path outside it.` For a root load, `<dir>` reads `the repository root`. |
| Missing or not a folder | `Driver directory '<dir>' does not exist in repository '<url>' (branch '<branch>', commit <sha>).` |
| No driver specification file | `No driver.styrmin.yml in driver directory '<dir>' of repository '<url>' (branch '<branch>', commit <sha>).` For a root load: `No driver.styrmin.yml at the root of repository '<url>' (branch '<branch>', commit <sha>).` |

`<sha>` is the full 40-character commit SHA. `<url>` is the repository URL without user info. The message never contains the temporary clone path or the target of a symlink.

## Propagation test

`backend/tests/functional/graphql/test_application_driver_version_propagation.py` (extended), per [`dev/guides/graphql-propagation-tests.md`](../../../dev/guides/graphql-propagation-tests.md):

- Write: build a local git repository in `tmp_path` with `drivers/a/` (the fixture driver), call the mutation with `repositoryUrl` = the repository path and `driverDirectory: "./drivers/a/"`, read the row back with `session.get` and assert `source_path == "drivers/a"` and `source_type == "git"`.
- Read: query `applicationDriver { versions { sourcePath } }` and assert `"drivers/a"`.
- Root load of the same repository without the argument: `source_path` is `NULL`.
- A refused value returns `VALIDATION_ERROR` and stores no row.

The Prefect manager is the existing `prefect_manager_mock` fixture.
