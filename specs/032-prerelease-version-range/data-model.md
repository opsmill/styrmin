# Data Model: Accept prerelease application versions that fit a driver version's range

**Spec**: [spec.md](spec.md) | **Research**: [research.md](research.md)

## Persistence

No change. No new table, no new column, no Alembic revision, no change to `backend/styrmin_backend/db/models.py`. `application_supported_versions` (`db/models.py:301`) and the stored application version of a deployment keep their type and content. Source: spec "Governance Gates Crossed" and research D1.

## Entities

### Application version (existing)

- **What it is**: the text of the version a person asked for, such as `1.12.0-beta.1`.
- **Stored as**: the string the person typed. Nothing normalises it (FR-003). `1.12.0-beta.1` is stored as `1.12.0-beta.1`, not as `1.12.0b1`.
- **Parsed as**: a PEP 440 version, only to be compared with a range. The parsed value is never stored.
- **Validation**: a string that is not a PEP 440 version fails to parse and behaves as today (research D4).

### Driver version range (existing field `application_supported_versions`)

- **What it is**: the range text of a driver version, such as `>=1.5,<2.0`.
- **Stored as**: unchanged text. The text is part of the identity key of a driver version (`DriverVersionKey.version` in `services/driver/hooks.py`), so it must not be rewritten.
- **Matching rule (new)**: a version fits a range when the range contains it with prereleases allowed. This is the only change.

### Version fit (new, not stored)

A pure yes-or-no answer to "does this parsed version fit this range text". It is computed on every request and never stored.

| Input | Output |
|---|---|
| a parsed PEP 440 version and a range text | `True` when the range contains the version with prereleases allowed, otherwise `False` |

Rules:

1. A stable version gives the same answer as before (FR-007).
2. A prerelease fits when its numbers fit. A prerelease of the lower bound (for example `1.12.0b0` against `>=1.12.0`) is below that bound and does not fit.
3. A prerelease of the exclusive upper bound (for example `2.0.0b1` against `<2.0`) does not fit.
4. An invalid range text raises as today. Ranges are validated when a driver loads (`validate_supported_versions`), so a stored range is valid.

Boundary cases (the shared check's unit table, verified with `packaging` 25.0 on 2026-11-10):

| Range | Version | Fits |
|---|---|---|
| `>=1.5,<2.0` | `1.12.0b0`, `1.9.0rc1`, `1.12.0.dev3`, `1.12.0-beta.1`, `1.12.0.b0`, `1.12.0_rc1`, `1.12.0` | yes |
| `>=1.5,<2.0` | `2.0.0b1`, `2.0.0rc1`, `1.5.0a1`, `1.5.0.dev1`, `1.4.0rc1` | no |
| `>=1.12.0,<1.13` | `1.12.0b0`, `1.9.0rc1`, `1.12.0.dev3` | no |
| `>=1.12.0b0,<1.13` | `1.12.0b0`, `1.12.0` | yes |
| `==1.12.0` | `1.12.0b0` | no |
| `!=1.12.0b0` | `1.12.0b1` | yes |

### Refusal (existing error type `InvalidVersionError`)

- **Error code**: `VALIDATION_ERROR` (`services/exceptions.py:163-167`), unchanged.
- **Content**: only the message text changes. See [contracts/refusal-messages.md](contracts/refusal-messages.md).

## State transitions

None. The feature adds no state and changes no lifecycle. A deployment moves between versions through the existing upgrade flow.
