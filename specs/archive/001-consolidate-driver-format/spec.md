# Feature Specification: Consolidate Driver Format

**Feature Branch**: `001-consolidate-driver-format`  
**Created**: 2026-04-02  
**Status**: Extracted  
**Input**: GitHub Issue #56 — Consolidate driver files into single driver.styrmin.yml

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Single-File Driver Authoring (Priority: P1)

As a driver author, I want all declarative configuration (driver spec and action declarations) in a single file so that I can author and review a driver without switching between multiple files.

Today, creating or modifying a driver requires editing up to 4 separate files (`styrmin_driver.yaml`, `chart_values.j2.yaml`, `actions.yaml`, `actions.py`), where references between `actions.yaml` and `actions.py` must be kept manually in sync. After this change, a driver author works with at most 3 files: `driver.styrmin.yml` (all declarative config), `values.j2.yml` (Helm values template), and optionally `actions.py` (action implementations).

**Why this priority**: This is the core value proposition — reducing cognitive load and file-sync errors for driver authors. Without this, the entire feature has no purpose.

**Independent Test**: Can be fully tested by creating a new driver using only the consolidated format and verifying the system loads and processes it correctly.

**Acceptance Scenarios**:

1. **Given** a driver directory with a valid `driver.styrmin.yml` containing both driver spec and action declarations, **When** the system loads the driver, **Then** all configuration (metadata, helm settings, components, parameters, services, and actions) is correctly parsed from the single file.
2. **Given** a driver with actions declared in `driver.styrmin.yml`, **When** the action references a function in `actions.py`, **Then** the system resolves and executes the action implementation correctly.
3. **Given** a driver directory without an `actions.py` file and no action declarations in `driver.styrmin.yml`, **When** the system loads the driver, **Then** the driver loads successfully without errors.

---

### User Story 2 - Renamed Values Template (Priority: P1)

As a driver author, I want the Helm values template to use the naming convention `values.j2.yml` so that the file naming is consistent and clearly communicates its purpose.

**Why this priority**: This is a required part of the format change and must ship alongside the consolidated config file to avoid a half-migrated state.

**Independent Test**: Can be tested by renaming the values template in an existing driver and verifying the system correctly locates and processes the renamed file.

**Acceptance Scenarios**:

1. **Given** a driver directory with a `values.j2.yml` file, **When** the system loads the driver, **Then** it reads the Helm values template from `values.j2.yml` instead of the old `chart_values.j2.yaml` filename.
2. **Given** a driver directory with both `chart_values.j2.yaml` and `values.j2.yml`, **When** the system loads the driver, **Then** the system reports an error indicating ambiguous configuration (only one values template should exist).

---

### User Story 3 - Example Driver Migration (Priority: P2)

As a platform operator or new driver author, I want all example drivers to use the new consolidated format so that I have accurate references when creating my own drivers.

**Why this priority**: Examples serve as de facto documentation. If they use the old format while the system expects the new format, they become misleading and cause confusion.

**Independent Test**: Can be tested by verifying each example driver directory contains only the new file structure and that all examples load successfully.

**Acceptance Scenarios**:

1. **Given** any example driver in the examples directory, **When** I inspect its contents, **Then** it contains `driver.styrmin.yml` (and optionally `values.j2.yml` and `actions.py`) with no references to the old filenames.
2. **Given** all migrated example drivers, **When** the system loads each one, **Then** every example driver loads and validates without errors.

---

### User Story 4 - Updated Documentation (Priority: P2)

As a driver author, I want the driver documentation to reflect the new file structure so that I can follow accurate instructions when creating or modifying drivers.

**Why this priority**: Documentation that contradicts the actual system behavior leads to support burden and author frustration.

**Independent Test**: Can be tested by reviewing the driver documentation and confirming all file references, directory structures, and examples match the new format.

**Acceptance Scenarios**:

1. **Given** the driver documentation, **When** a driver author reads it, **Then** all file structure descriptions, examples, and references use the new filenames (`driver.styrmin.yml`, `values.j2.yml`).
2. **Given** the driver documentation, **When** it describes how to add actions to a driver, **Then** it shows actions as a section within `driver.styrmin.yml` rather than as a separate file.

---

### Edge Cases

- What happens when a driver directory contains the old filenames (`styrmin_driver.yaml`, `actions.yaml`, `chart_values.j2.yaml`) but not the new ones? The system should report a clear error indicating the driver uses a deprecated format.
- What happens when a driver directory contains both old and new filenames (e.g., both `styrmin_driver.yaml` and `driver.styrmin.yml`)? The system should report an error indicating ambiguous configuration.
- What happens when `driver.styrmin.yml` declares actions but no `actions.py` file exists? The system should report a validation error indicating missing action implementations.
- What happens when `driver.styrmin.yml` is empty or malformed? The system should report a clear parsing/validation error.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST load all declarative driver configuration (metadata, helm settings, components, parameters, services, and action declarations) from a single `driver.styrmin.yml` file.
- **FR-002**: System MUST load the Helm values template from a file named `values.j2.yml`.
- **FR-003**: System MUST validate that action declarations in `driver.styrmin.yml` have corresponding implementations in `actions.py` when actions are present.
- **FR-004**: System MUST report a clear error when a driver directory contains neither the new nor the old expected filenames.
- **FR-005**: System MUST report a clear error when a driver directory contains ambiguous configurations (both old and new filenames for the same purpose).
- **FR-006**: System MUST successfully load drivers that have no actions (no action declarations and no `actions.py`).
- **FR-007**: System MUST successfully load drivers that have no Helm values template (no `values.j2.yml`).
- **FR-008**: All example drivers MUST be migrated to use the new file structure.
- **FR-009**: Driver documentation MUST be updated to reflect the new file structure and naming conventions.

### Key Entities

- **Driver Specification (`driver.styrmin.yml`)**: The single declarative configuration file containing apiVersion, kind, metadata, helm configuration, components, parameters, services, and action declarations. Replaces the separate `styrmin_driver.yaml` and `actions.yaml` files.
- **Values Template (`values.j2.yml`)**: Jinja2 template for Helm chart values. Renamed from `chart_values.j2.yaml`. Remains an independent file due to its templating nature.
- **Action Implementation (`actions.py`)**: Python file containing action implementations (Prefect flows). Unchanged in structure, only present when actions are declared.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A complete driver can be understood by reading at most 3 files (down from 4), with all declarative configuration in a single file.
- **SC-002**: Driver authors no longer need to manually keep action declarations and a separate actions configuration file in sync, eliminating a class of authoring errors.
- **SC-003**: 100% of example drivers use the new consolidated format and load without errors.
- **SC-004**: All existing system tests pass or are updated to reflect the new format with no regressions.
- **SC-005**: New driver authors can create a working driver by following the updated documentation without encountering references to deprecated filenames.

## Assumptions

- The `actions.py` file structure and its role as the Python implementation of actions remains unchanged. Only the declarative configuration is being consolidated.
- The content currently in `actions.yaml` (action declarations — hook types, names, references to Python functions) can be represented as a section within the YAML structure of `driver.styrmin.yml` without loss of information.
- There is no need for a migration tool or backward compatibility period — all drivers will be migrated as part of this feature, and the old format will no longer be supported.
- The Jinja2 values template remains a separate file because it serves a fundamentally different purpose (templating) and mixing Jinja2 syntax within a YAML configuration file would reduce clarity.
