# Contract: refusal messages for an unsupported application version

**Spec**: [spec.md](../spec.md) (FR-004, FR-005, FR-006) | **Research**: [research.md](../research.md) (D5)

No GraphQL schema, SDK model or CLI command changes. The only interface that changes is the text of an existing error. `schema.graphql` is not regenerated, and the SDK types are not regenerated, because no field, argument, type or mutation changes. Source: spec "Governance Gates Crossed".

## Error identity (unchanged)

- Service error: `InvalidVersionError` (`backend/styrmin_backend/services/exceptions.py:163`).
- GraphQL `extensions.code`: `VALIDATION_ERROR`.
- No resource is created when the error is raised. The check runs before anything is dispatched (`deployment.py`, comment "Validate everything against the target versions before anything is dispatched").

## Message 1: no driver version supports the version (create and upgrade without a pin)

```text
Version {version} is not supported by the application driver {driver} (supported ranges: {range_1}, {range_2}).
```

- `{version}`: the string as the person typed it.
- Ranges: every distinct `application_supported_versions` of the driver, newest driver version first (the order of `_driver_version_sort_key`), separated by `, `, each listed once.
- A driver with no driver versions: the parenthesis is left out.
- Example for the standard driver and `2.0.0b1`: `Version 2.0.0b1 is not supported by the application driver infrahub (supported ranges: >=1.5,<2.0).`

## Message 2: the pinned driver version does not support the version

```text
Version {version} is not supported by driver version {driver_version_id} (supports {pinned_range}). Supported ranges of the application driver {driver}: {range_1}, {range_2}.
```

- The first sentence is today's text with a closing period.
- The second sentence is new, so that the refusal lists every range of the driver (FR-004, SC-003).
- Example: `Version 2.0.0b1 is not supported by driver version 3f2c… (supports >=1.5,<2.0). Supported ranges of the application driver infrahub: >=1.5,<2.0.`

## Rules for both messages

- The message names the version and lists the ranges (FR-004). A test asserts both.
- The message does not contain the word "prerelease" and does not say that a range must name one (FR-005). A test asserts the absence of the word for a prerelease request.
- The message is never produced for a version that fits a range, at any place (FR-002).

## Not changed

- `No version specified and no default version found for driver {driver}` and `No version specified and pinned driver version {id} declares no default version`: unchanged.
- `Driver version {id} does not belong to application driver {name}; cross-driver moves are not supported`: unchanged.
- The driver-load message `default_version '{v}' does not satisfy supported_versions '{range}'`: unchanged text, now raised only when the default does not fit with prereleases allowed.
- The outcome for a string that is not a PEP 440 version (FR-006): unchanged. A characterization test records it before the code changes (research D4).
