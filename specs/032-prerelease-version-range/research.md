# Research: Accept prerelease application versions that fit a driver version's range

**Spec**: [spec.md](spec.md) | **Date**: 2026-11-10

Every statement below names the file, command or document that supports it. A statement without a source is marked "not verified".

## Third-party dependency evaluation (required by the prep workflow)

Styrmin matches an application version against a range with `packaging.specifiers.SpecifierSet`. By default `SpecifierSet.contains()` admits a prerelease only when a clause of the range names one ([PEP 440, handling of pre-releases](https://peps.python.org/pep-0440/#handling-of-pre-releases)). The default does not support what this feature needs, so the dependency was evaluated before a design was chosen.

### Decision D1: use the built-in `prereleases=True` argument of `packaging`

- **Chosen approach**: call `SpecifierSet(range).contains(version, prereleases=True)` in one shared function. The argument is part of the public `packaging` API, so no extension, patch or workaround is needed.
- **Rationale**:
  - Verified locally with `packaging` 25.0 (`uv run python`, 2026-11-10): `>=1.5,<2.0` accepts `1.12.0b0`, `1.9.0rc1`, `1.12.0.dev3`, `1.12.0-beta.1`, `1.12.0.b0`, `1.12.0_rc1` and `1.12.0`. It refuses `2.0.0b1`, `2.0.0rc1`, `1.5.0a1`, `1.5.0.dev1` and `1.4.0rc1`. `>=1.12.0,<1.13` refuses `1.12.0b0`, `1.9.0rc1` and `1.12.0.dev3`. `>=1.12.0b0,<1.13` accepts `1.12.0b0` and `1.12.0`. This is the same table as the PRD edge cases.
  - The argument only widens what counts as a candidate. The ordering rules of PEP 440 still apply, so a prerelease of the upper bound stays outside `<2.0`.
  - `packaging` 25.0 is already installed in the repository (`uv run python -c "import packaging"` prints `25.0`).
- **Alternatives rejected**:
  - *Extension mechanism of `packaging`*: none exists and none is needed, because the library already exposes the flag.
  - *Upstream contribution*: not needed, because the flag exists.
  - *Rewrite a range at load time to name a prerelease (for example append `,>=0.0.0a0`)*: this changes the stored `application_supported_versions` text and the driver fingerprint identity, which is the driver-side workaround that Fatih rejected and that [Constitution II](../../dev/constitution.md) and the user's Styrmin design preference advise against.
  - *Change the standard drivers' ranges*: rejected by the PRD (out of scope) and by the same design preference. Styrmin's own version check can solve the problem, so the driver model stays unchanged.
  - *A request-level opt-in flag for prereleases*: rejected by the PRD (out of scope).

## Where the version is checked today

All locations are in `backend/styrmin_backend/` on the branch `sas-591-prerelease-spec` at `5abe5647`.

| Place | Code | Used by |
|---|---|---|
| Choosing the driver version for a version | `_resolve_latest_matching_version`, `services/deployment.py:785-803`, uses `target in SpecifierSet(...)` | creating a deployment (`deploy_application`, near line 1890) and upgrading (`update_deployment_version`, near line 986) |
| Checking a pinned driver version | `_ensure_pin_supports_version`, `services/deployment.py:825-833`, uses `Version(version) not in SpecifierSet(...)` | creating with a pin (near line 1867) and upgrading with a pin (near line 976) |
| Checking the default version of a driver at load | `validate_default_version`, `services/driver/models/resources/driver.py:341-350`, uses `Version(self.default_version) not in specifier` | every driver load (the pydantic model of the driver file) |
| Refusal when no driver version supports the version | `InvalidVersionError` raised at `services/deployment.py:989` and `:1901` with the bare message | create and upgrade without a pin |

Findings:

- There are exactly three places that test a version against a range. The PRD's "four places" (create, upgrade, pin, driver load) map onto them, because create and upgrade share the first two. A grep for `SpecifierSet` over `backend/styrmin_backend` finds no other use (`rg`-equivalent `grep -rn "SpecifierSet"`, 2026-11-10).
- `services/driver/hooks.py` and `services/applications.py` use `supported_versions` only as a key and a stored string, not to match a version.
- The unpinned refusal at `deployment.py:989` and `:1901` has no range list. The pin refusal already prints the range of the pinned driver version.

## Open pull request #594

[PR #594](https://github.com/opsmill/styrmin/pull/594) (open, base `develop`, head `fix/591-prerelease-refusal-message`, commit `fd90f8db`) is not in this branch. It contains:

- `_unsupported_version_error` and `_prerelease_explanation` in `services/deployment.py`. The first lists every range newest driver version first, without duplicates. The second explains the old rule.
- Documentation `docs/docs/drivers/creating-a-driver.md` ("Prereleases in `supported_versions`") and a link in `loading-drivers.md`.
- A glossary entry "Prerelease" in `CONTEXT.md` that states the old rule.
- A changelog fragment `changelog/591.changed.md`.
- Unit tests `test_unsupported_version_message.py` and additions to `test_driver_version_resolution.py`.
- An E2E node `backend/tests/e2e/test_prerelease_version.py` and a helper `publish_simple_app_driver_build` in `backend/tests/e2e/helpers/drivers.py`.

Checked: `git merge-tree --write-tree` of this branch and `origin/fix/591-prerelease-refusal-message` returns a tree id with no conflict (2026-11-10).

### Decision D2: build this change on top of the #594 commit

- **Chosen approach**: the first implementation task brings `fd90f8db` onto this branch with `git cherry-pick`, which keeps its authorship. The change then reworks the pieces whose meaning changed: the explanation text goes, the range list stays, the documentation section and the glossary entry are rewritten, and the tests and the E2E node are reworked.
- **Rationale**: the PRD names #594 as "related pull request to rework" and as the base of the message. The range list, the documentation page, the changelog fragment and the E2E helper are reusable as they are. The cherry-pick applies without conflict.
- **Alternatives rejected**:
  - *Rewrite everything from `develop` without #594*: repeats finished work and loses the review history.
  - *Wait for #594 to merge first*: #594 encodes the rule that this feature removes. Merging it first would ship a documented rule that a second change then reverses.
- **Not decided here**: what happens to the pull request #594 itself (closed in favour of a new one, or updated). That is a decision for the maintainers. The plan only needs the commit.

## Decisions

### D3: one shared check, with the parsed version supplied by the caller

- **Chosen approach**: a new function `version_fits_range(version: Version, supported_versions: str) -> bool` in a new module `backend/styrmin_backend/services/version_range.py`. It returns `SpecifierSet(supported_versions).contains(version, prereleases=True)`. The three places call it. Each caller parses the version string as it does today.
- **Rationale**:
  - One function gives the same verdict at every place (FR-002), and one table of boundary cases tests it (SC-002).
  - The module has no dependency but `packaging`, so the driver model can import it without a cycle. `driver.py` already imports `styrmin_backend.services.exceptions`, which shows that importing from `styrmin_backend.services` is allowed. `services/__init__.py` holds only a docstring and imports nothing (read 2026-11-10), so a new module there creates no import cycle.
  - Parsing stays at the call site, so the type of error for an invalid version does not change (see D4).
- **Alternatives rejected**:
  - *Set `prereleases=True` at each of the three places*: three copies of the rule can drift. FR-002 asks for one rule.
  - *Store the `SpecifierSet` with prereleases on the driver version model*: persistence and model changes, which the PRD excludes.

### D4: a version that is not valid under PEP 440 behaves as today

- **Fact**: `Version("latest")` and `Version("develop")` raise `packaging.version.InvalidVersion` (checked locally, `packaging` 25.0). In `_resolve_latest_matching_version` and `_ensure_pin_supports_version` the call `Version(...)` is not wrapped, so the exception is raised from the service function. How the GraphQL layer reports it was not verified.
- **Decision**: keep the parse at the call site and do not catch the error, so the behaviour is unchanged (FR-006). The first task writes a characterization test that records today's outcome for `latest` before any code changes, and the same test must still pass afterwards.
- **Rationale**: the PRD says such versions "are refused as today" and puts non-semver tags out of scope.

### D5: the refusal message lists every range and never explains a prerelease rule

- **Chosen approach**: keep `_unsupported_version_error` from #594 (range list, newest driver version first, no duplicates, no list when the driver has no versions) and delete `_prerelease_explanation`. The pin refusal gets the same list of ranges of the application driver. The exact texts are in [contracts/refusal-messages.md](contracts/refusal-messages.md).
- **Rationale**:
  - FR-004 and SC-003 say that every refusal lists all supported ranges of the driver. Today the pin refusal lists only the range of the pinned driver version, so it needs the driver's ranges added.
  - FR-005: with the new rule, a refusal is never caused by a missing prerelease clause, so the explanation would be false.
  - The application driver is available at both pin call sites (`update_deployment_version` loads it at `deployment.py:963-966`; `deploy_application` has `application`). This was read in the code; the helper's signature change is verified when it is written.
- **Alternatives rejected**: keep the pin message as it is (fails FR-004 and SC-003 as the spec states them).

### D6: End-to-end coverage extends `test_deploy_app.py` and reuses the session driver

- **Facts**:
  - The session `simple-app` driver has `supported_versions: ">=0.1,<1.0"` (`driver/examples/simple-app/driver.styrmin.yml:8`), a range that names no prerelease.
  - Its values template uses `{{ app.version }}` as the image tag (`driver/examples/simple-app/values.j2.yml:5`).
  - The fixture `simple_app_image` builds `simple-app:0.1.0`, and `simple_app_image_v2` builds `simple-app:0.2.0` (`backend/tests/e2e/conftest.py:1158-1205`).
  - The E2E in #594 passed with a docker re-tag of the session image to `simple-app:0.2.0b0` (PR description, "Testing"; the pass was reported by that PR, not re-run here).
- **Chosen approach**: add one test node to `backend/tests/e2e/test_deploy_app.py` that uses the session driver unchanged and the session environment fixtures:
  1. re-tag the session image to the exact string typed, `0.2.0-beta.1` (a PEP 440 non-canonical spelling, so that "stored as typed" is a real assertion);
  2. create a deployment of `0.2.0-beta.1`, wait for running, read the stored application version (US1, FR-003);
  3. upgrade it to `0.2.0` (US2, follow a beta to its release);
  4. request `1.0.0b1` and assert the refusal text and that no deployment is created (US3, FR-004).
  Pin coverage stays in unit tests; the pin call site is the same service function.
- **Rationale**: no second build of a driver, no new heavy fixture. The test needs only a docker tag and one deployment on a stack that the file already deploys. Constitution V and the "Reuse before you boot" rule prefer extending an existing file over a new node that boots its own stack. #594 needed a new driver name because the old rule required a second range; the new rule does not.
- **Alternative considered**: extend `test_upgrade_simple_app` (`0.1.0` to `0.2.0`) to pass through a beta. Rejected as the only change, because it covers upgrade but not creation of a prerelease, which is the P1 journey. The new node covers both.
- **Open at plan time (resolves the PRD open questions)**:
  - *Does the chart accept a beta string?* The values template uses the version as an image tag, and the docker re-tag makes `0.2.0-beta.1` a valid image. A docker tag may contain letters, digits, `.`, `-` and `_`. The first implementation task confirms by running the node.
  - *Can the UI variant run it?* Not verified. #594 states that "it is not known whether the Deploy form accepts a prerelease version". The task tries the `[ui-chromium]` variant with the dual-entrypoint `scenario_driver` methods. If the form refuses the string, the node is marked `api_only` with that reason. If the UI variant works, it stays dual-entrypoint, because it then exercises both entrypoints.
  - The shard marker is the one already carried by `test_deploy_app.py` (the task reads the file's `pytestmark`).

### D7: the CLI, SDK and UI show the message as the API returns it

- **Fact**: #594's E2E asserts the text through `StyrminAPIError` from the SDK (`str(refused.value)`), so the SDK carries the text. How `styrminctl` and the UI render a longer message was not verified.
- **Decision**: no code change is planned for either surface, as in the PRD. The implementation checks both once with a refused request and records what it sees in the quickstart results. A rendering defect found there becomes a separate issue, because the PRD limits this feature to the text of the error.

### D8: documentation and glossary

- **Chosen approach**: rework #594's documentation section "Prereleases in `supported_versions`" in `docs/docs/drivers/creating-a-driver.md` to state the new rule: a range accepts a prerelease when its numbers fit; PEP 440 orders a prerelease below its release, so `>=1.12.0,<1.13` refuses `1.12.0b0`; write `>=1.12.0b0,<1.13` to accept the prereleases of 1.12.0 (User Story 4). Update the link text in `loading-drivers.md`. Rewrite the glossary entry "Prerelease" and extend "Application version" in `CONTEXT.md`. Rewrite the changelog fragment `changelog/591.changed.md`. Constitution VII requires these in the same change.
- **Note**: the documentation also has to say that stable ranges now accept prereleases inside them, for example `>=1.5,<2.0` accepts `1.9.0rc1`, so authors who do not want that know it is the rule. A way to forbid prereleases is out of scope (spec).

### D9: the default version of a driver

- **Chosen approach**: `validate_default_version` calls the shared function, so a driver whose `default_version` is a prerelease that fits its range loads. A request without a version then uses that default through the same code (`deploy_application`, `deployment.py:1870-1888`), which the shared function accepts.
- **Not verified**: the PRD states that a prerelease default "was not tested yet". The unit tests in the tasks cover the driver load. The path through a deployment without a version is covered by a unit test of `deploy_application` with a prerelease default.

## Items for the maintainers

- What happens to pull request #594 (close, or update to carry this change) is not decided here.
- The E2E UI variant result (D6) is open until the node runs.
