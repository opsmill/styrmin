# ADR-068: Invalid `spec.info` Icon and Links Values Are Dropped With a Load Warning, Not a Load Failure

**Status**: Accepted
**Date**: 2026-10-13
**Source**: commit `8a166997` (review of PR #418 for [issue #272](https://github.com/opsmill/styrmin/issues/272)); specs/archive/020-driver-info-display/ (research R3, spec FR-003 to FR-005 and Assumptions)
**Related**: [ADR-067](0067-driver-logos-loaded-by-the-viewer-browser.md) (the rules an `icon` or link URL must meet). This ADR replaces research R3 of specs/archive/020-driver-info-display, which made an invalid value fail the load.

## Context

Spec 020 started to store `spec.info.icon`, `spec.info.description` and `spec.info.links` on each application driver version (ADR-067). Research R3 and FR-003 to FR-005 validated the URLs with Pydantic `HttpUrl` and made an invalid `icon` or `links` entry fail the whole load, with an error that named the field.

The spec's Assumptions noted the cost: driver files that copied the `icon: xxxx` placeholder from the earlier `driver/DRIVERS.md` and example drivers would no longer load. During the review of PR #418, commit `8a166997` changed the behaviour so that such files load again.

## Decision

1. **A wrap validator on `Info`** (`_drop_invalid_icon_and_links` in `services/driver/models/resources/driver.py`) removes invalid values before Pydantic validates the block:
   - an `icon` that is not an absolute `https` URL, or that contains a username or password;
   - each `links` entry that is not a mapping with exactly the keys `link` and `url`, whose `link` is not text, or whose `url` is not an absolute `http` or `https` URL or contains a username or password. Each entry is checked on its own, and the valid entries are kept;
   - a `links` value that is not a list, as a whole.
2. **Each dropped value produces one warning** that names the field path, such as `spec.info.links[1].url`, and says that the value was not stored. A warning about a URL with a username or password does not repeat the URL.
3. **The load succeeds.** `_store_loaded_driver` (`services/applications.py`) logs each warning. The two load mutations return the warnings in `ApplicationDriverVersion.loadWarnings`, which is empty in every other response. `styrminctl drivers load-version` and `load-local-version` print them, and the Load driver drawer shows them in a notification that stays until the user closes it.
4. **Warnings are not stored.** Loading the same file again returns them again.
5. **Any other invalid field still fails the load.** The error lists one line per invalid field, with its path, the problem and the value found (`format_validation_error` in `services/driver/deserializers.py`).

## Consequences

- Driver files that loaded before spec 020 still load, including files with `icon: xxxx`.
- A driver author learns that a value was dropped only from the load result: the CLI output, the notification in the Load driver drawer, or the server log. After the notification is closed, no page shows the warnings.
- An `http` icon, which the specification accepted, is now dropped with a warning (ADR-067 decision 4).

## Alternatives Considered

- **Fail the load with an error that names the field** (research R3, FR-003 to FR-005): the original design, replaced because it broke driver files that loaded before, such as files with `icon: xxxx` (commit `8a166997`).
- The sources record no other alternative, such as storing the warnings on the driver version.
