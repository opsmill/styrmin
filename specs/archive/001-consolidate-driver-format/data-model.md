# Data Model: Consolidate Driver Format

**Feature Branch**: `001-consolidate-driver-format`  
**Date**: 2026-04-02

## Entity Changes

This feature does not introduce new database entities. All changes are to in-memory Pydantic models used during driver loading.

### Modified Entity: Specification (driver.py)

The `Specification` model gains an optional `actions` field.

**Current fields**: `version`, `supported_versions`, `default_version`, `info`, `helm`, `components`, `parameters`, `services`

**Added field**:
- `actions`: Optional list of `ActionDefinition` — action declarations previously in a separate `actions.yaml` file. Defaults to empty list when absent.

**Validation rules**:
- Each `ActionDefinition.location` must match pattern `^[a-zA-Z0-9][a-zA-Z0-9_-]*\.py::[a-z_][a-zA-Z0-9_]+$`
- Each `ActionDefinition.hook` must be a valid `HookKind` (SETUP or UPGRADE)
- Each `ActionDefinition.name` must be unique within the actions list
- If `actions` is non-empty, `actions.py` must exist in the driver directory (validated post-deserialization)

### Removed Entity: ActionsSpec (actions.py)

The `ActionsSpec` envelope model (`apiVersion`, `kind: ActionDefinition`, `metadata.package`, `spec.actions`) is removed. Its inner `ActionDefinition` model is preserved and reused.

**Removed models**: `ActionsSpec`, `ActionsSpec.Metadata`, `ActionsSpec.Spec`  
**Preserved models**: `ActionDefinition`, `HookKind`, `ParameterKind`, `Parameter`

### Modified Entity: DriverDirectory (directory.py)

**Current resource files**: `driver_spec`, `values_template`, `actions_spec`, `actions_code`

**New resource files**: `driver_spec`, `values_template`, `actions_code`

- `driver_spec`: Path changes from `styrmin_driver.yaml` to `driver.styrmin.yml`
- `values_template`: Path changes from `chart_values.j2.yaml` to `values.j2.yml`, becomes optional
- `actions_spec`: **Removed** — no longer a separate file
- `actions_code`: Unchanged (`actions.py`), remains optional

### Modified Entity: ApplicationDriver (__init__.py)

**Current fields**: `source`, `driver_spec`, `values_template`, `actions_spec`

**New fields**: `source`, `driver_spec`, `values_template`

- `actions_spec` field is removed — action information is now accessible via `driver_spec.spec.actions`

### Modified Entity: DriverSettings (config.py)

**Current settings**: `spec_file`, `chart_values_template`, `actions_spec_file`, `actions_code_file`

**New settings**: `spec_file` (default: `driver.styrmin.yml`), `values_template` (default: `values.j2.yml`), `actions_code_file` (default: `actions.py`)

- `actions_spec_file` is removed
- `chart_values_template` is renamed to `values_template`

### Modified Enum: Role (resource.py)

**Current values**: `DRIVER_SPEC`, `ACTIONS_SPEC`, `VALUES_TEMPLATE`, `ACTIONS_CODE`

**New values**: `DRIVER_SPEC`, `VALUES_TEMPLATE`, `ACTIONS_CODE`

- `ACTIONS_SPEC` is removed

### Modified Type Alias: DriverResource

**Current**: `ActionsSpec | DriverSpec | ActionsCode | str`

**New**: `DriverSpec | ActionsCode | str`

## New Error Types

- **DeprecatedDriverFormatError**: Raised when old filenames are detected without new ones. Contains list of old files found and migration instructions.
- **AmbiguousDriverFormatError**: Raised when both old and new filenames exist in the same directory.

## Consolidated YAML Schema

```yaml
# driver.styrmin.yml
apiVersion: "styrmin.io/v1"        # Required, must be "styrmin.io/v1"
kind: ApplicationDriver             # Required, must be "ApplicationDriver"
metadata:
  name: <string>                    # Required, driver identifier
spec:
  version: <string>                 # Required
  supported_versions: <string>      # Required, semver range
  default_version: <string>         # Optional
  info:                             # Optional
    description: <string>
    authors: [<string>]
    license: <string>
    icon: <string>
    links:
      - link: <string>
        url: <string>
  helm:
    main:
      location: <string>           # Required
      version: <string>            # Required
  components:                       # Required
    <component-name>:
      cpu: <integer>               # Optional
      identifier:
        label:
          <key>: <value>
      backup:                      # Optional
        enabled: <boolean>
        kind: <BackupKind>
        database_name: <string>
        # ... other backup fields
  parameters:                      # Optional
    - name: <string>
      label: <string>
      kind: <ParameterKind>
      default: <any>
  services:                        # Optional
    - name: <string>
      kind: <string>
      scope: <string>
      port: <integer>
      component: <string>
  actions:                         # Optional (NEW — merged from actions.yaml)
    - name: <string>
      hook: <HookKind>             # setup | upgrade
      mode: <string>               # pre | core | post
      description: <string>
      location: <string>           # Pattern: "filename.py::function_name"
      parameters:                  # Optional
        - name: <string>
          kind: <ParameterKind>
          mandatory: <boolean>
      image: <string>              # Optional
```
