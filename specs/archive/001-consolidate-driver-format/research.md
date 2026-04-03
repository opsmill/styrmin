# Research: Consolidate Driver Format

**Feature Branch**: `001-consolidate-driver-format`  
**Date**: 2026-04-02

## R1: Consolidated YAML Schema Design

**Decision**: Embed action declarations as an `actions` key within the existing `spec` section of the `ApplicationDriver` YAML document. The `ActionDefinition` kind and its separate `apiVersion`/`kind`/`metadata` envelope are eliminated.

**Rationale**: The current `actions.yaml` wraps action definitions in a separate Kubernetes-style envelope (`apiVersion`, `kind: ActionDefinition`, `metadata.package`). Since the actions are always tightly coupled to a single driver, this envelope adds no value. Inlining them under `spec.actions` keeps the structure flat and avoids a multi-document YAML file or nested kind declarations.

**Alternatives considered**:
- **Multi-document YAML** (two `---` documents in one file): Rejected because it requires parsing multiple documents and doesn't simplify the model — just collapses files.
- **Nested kind** (embed full `ActionDefinition` as a sub-object): Rejected because it preserves unnecessary envelope boilerplate (`apiVersion`, `kind`, `metadata`) inside the parent document.

**Proposed consolidated structure**:
```yaml
apiVersion: "styrmin.io/v1"
kind: ApplicationDriver
metadata:
  name: simple-app
spec:
  version: "1"
  supported_versions: ">=0.1,<1.0"
  # ... existing helm, components, parameters, services ...
  actions:
    - name: upgrade
      hook: upgrade
      mode: core
      description: Upgrade Simple App
      location: "actions.py::upgrade"
```

The `metadata.package` from `actions.yaml` is dropped — `metadata.name` from the driver spec serves the same purpose.

## R2: File Naming Convention

**Decision**: Use `.yml` extension (not `.yaml`) for both `driver.styrmin.yml` and `values.j2.yml`.

**Rationale**: The issue explicitly specifies `.yml` extension. This is consistent with Kubernetes ecosystem conventions (e.g., `kustomization.yml`). The `.styrmin.` infix in `driver.styrmin.yml` clearly identifies it as a Styrmin-specific file, analogous to `docker-compose.yml` or `.gitlab-ci.yml`.

**Alternatives considered**:
- `.yaml` extension: Rejected per issue requirements, though functionally equivalent.
- `driver.yml` (without `.styrmin.` infix): Rejected because it's too generic and could conflict with other tools.

## R3: Backward Compatibility Strategy

**Decision**: No backward compatibility. Old filenames produce clear error messages. No migration tool.

**Rationale**: Per the spec assumptions, all drivers (including examples) are migrated as part of this feature. The driver ecosystem is internal and the number of drivers is small enough to migrate manually. Supporting both formats would double the validation and testing surface for no ongoing benefit.

**Alternatives considered**:
- **Dual-format support with deprecation warnings**: Rejected — increases complexity of the loader pipeline and defers cleanup.
- **Automatic migration tool**: Rejected — the number of drivers is small, and the merge logic is straightforward enough to do by hand or in the PR.

## R4: Config Settings Refactoring

**Decision**: Replace the four filename settings (`spec_file`, `chart_values_template`, `actions_spec_file`, `actions_code_file`) with two: `spec_file` (default: `driver.styrmin.yml`) and `values_template` (default: `values.j2.yml`). Keep `actions_code_file` (default: `actions.py`) since it's still a separate file.

**Rationale**: Three settings map to three physical files. The `actions_spec_file` setting is eliminated because action declarations are now part of the spec file. Keeping settings configurable via environment variables preserves operational flexibility.

**Alternatives considered**:
- **Single setting for everything**: Rejected because the values template and actions code are still separate files that need independent path configuration.
- **Remove all settings, hardcode filenames**: Rejected because environment-based overrides are a useful operational pattern.

## R5: Pydantic Model Merging Strategy

**Decision**: Add an optional `actions` field to the existing `Specification` model (in `models/resources/driver.py`) that holds a list of `ActionDefinition` objects (reused from the existing `models/resources/actions.py` module). Remove the `ActionsSpec` envelope model.

**Rationale**: The `ActionDefinition` model is well-defined and tested. By embedding it directly in `Specification`, we avoid creating a new model and preserve all existing field validation (name patterns, location regex, hook enum, mode enum). The `ActionsSpec` envelope (`apiVersion`, `kind`, `metadata`, `spec`) is no longer needed since these fields are already present on the parent `DriverSpec`.

**Alternatives considered**:
- **New `ConsolidatedSpecification` model**: Rejected — unnecessary when the existing `Specification` model can be extended with one field.
- **Keep `ActionsSpec` as embedded sub-model**: Rejected — preserves the unnecessary envelope structure.

## R6: Loader Pipeline Simplification

**Decision**: Simplify `DriverDirectory` to define three resource files: `driver_spec` (YAML, required), `values_template` (STR, optional), and `actions_code` (PYTHON, optional). The `actions_spec` resource is eliminated. The loader extracts actions from the deserialized `DriverSpec` model rather than loading a separate file.

**Rationale**: With actions embedded in the spec YAML, the loader no longer needs a separate parse→validate→deserialize pipeline for `actions.yaml`. The `UserActionsValidator` (which cross-references action declarations against `actions.py` function definitions) moves to a post-deserialization validation step that operates on the deserialized `DriverSpec.spec.actions` field.

**Alternatives considered**:
- **Keep 4-resource pipeline, just point two at the same file**: Rejected — adds complexity for no benefit and requires the YAML to be parsed twice.

## R7: Error Detection for Old Format

**Decision**: After failing to find `driver.styrmin.yml`, the loader checks for `styrmin_driver.yaml` (old spec) or `actions.yaml` (old actions) or `chart_values.j2.yaml` (old values). If any are found, raise a specific `DeprecatedDriverFormatError` with a message listing the old files found and instructions to migrate. If both old and new files exist, raise an `AmbiguousDriverFormatError`.

**Rationale**: Clear error messages accelerate troubleshooting and make the migration path obvious. Checking for old filenames is cheap (filesystem stat) and prevents confusing "file not found" errors.

**Alternatives considered**:
- **Silent fallback to old format**: Rejected per R3 decision.
- **Generic "file not found" error**: Rejected — unhelpful for users who haven't migrated yet.
