# ADR-002: Consolidate Driver Declarative Config Into Single YAML File

**Status**: Accepted
**Date**: 2026-04-03
**Source**: specs/archive/001-consolidate-driver-format/research.md (R1, R2, R4, R5, R6)

## Context

Application drivers required up to 4 files (`styrmin_driver.yaml`, `actions.yaml`, `chart_values.j2.yaml`, `actions.py`), where action declarations in `actions.yaml` had to be manually kept in sync with implementations in `actions.py`. The separate `actions.yaml` wrapped action definitions in a Kubernetes-style envelope (`apiVersion`, `kind: ActionDefinition`, `metadata.package`) that added no value since actions are always tightly coupled to a single driver. This multi-file structure increased cognitive load and created a class of authoring errors from cross-file sync failures.

## Decision

Consolidate all declarative driver configuration into a single `driver.styrmin.yml` file:

1. **Schema**: Embed action declarations as `spec.actions` within the existing `ApplicationDriver` YAML document, eliminating the `ActionDefinition` kind envelope.
2. **Naming**: Use `.yml` extension with `.styrmin.` infix (`driver.styrmin.yml`) to clearly identify Styrmin-specific files. Rename the values template from `chart_values.j2.yaml` to `values.j2.yml`.
3. **Settings**: Reduce `DriverSettings` from 4 filename settings to 3 (`spec_file`, `values_template`, `actions_code_file`), removing `actions_spec_file`.
4. **Models**: Add an optional `actions: list[ActionDefinition]` field to the existing `Specification` model rather than creating a new model. Remove the `ActionsSpec` envelope model.
5. **Loader pipeline**: Simplify `DriverDirectory` from 4 resource files to 3 (`driver_spec`, `values_template`, `actions_code`), removing the separate `actions_spec` resource. Actions are extracted from the deserialized `DriverSpec` model.

A complete driver now consists of at most 3 files: `driver.styrmin.yml` (all declarative config), `values.j2.yml` (Helm values template, optional), and `actions.py` (action implementations, optional).

## Consequences

- Driver authors work with fewer files and no longer need to keep action declarations in sync across files.
- The loader pipeline is simpler with one fewer parse-validate-deserialize path.
- The `ActionsSpec` model and `ACTIONS_SPEC` role are removed, reducing the model surface.
- All existing drivers must be migrated to the new format (a one-time cost).
- The Jinja2 values template remains a separate file because mixing Jinja2 syntax within a YAML configuration file would reduce clarity.

## Alternatives Considered

- **Multi-document YAML** (two `---` documents in one file): Rejected because it requires parsing multiple documents and doesn't simplify the model.
- **Nested kind** (embed full `ActionDefinition` as a sub-object with its own `apiVersion`/`kind`/`metadata`): Rejected because it preserves unnecessary envelope boilerplate.
- **`.yaml` extension**: Rejected per project requirements; `.yml` is consistent with Kubernetes ecosystem conventions.
- **`driver.yml` without `.styrmin.` infix**: Rejected as too generic and could conflict with other tools.
- **New `ConsolidatedSpecification` model**: Rejected when the existing `Specification` model can be extended with one field.
- **Keep 4-resource pipeline, point two at the same file**: Rejected as it adds complexity and requires parsing the YAML twice.
