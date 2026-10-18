# ADR-080: Action Deployments of a Driver Directory Version Carry a `directory/` Tag and a Digest in Their Name

**Status**: Accepted
**Date**: 2026-10-18
**Decision-makers**: Fatih Acar
**Source**: specs/archive/028-git-driver-directory/research.md (R-003);
[issue #517](https://github.com/opsmill/styrmin/issues/517); [PR #529](https://github.com/opsmill/styrmin/pull/529)
**Related**: [ADR-053](0053-driver-version-provenance-fingerprint.md) (a git driver version is
identified by the commit of the whole repository),
[ADR-079](0079-driver-actions-import-only-from-their-driver-directory.md) (actions run from their
driver directory)

## Context

When a driver is loaded from git, `PrefectManager.register_user_action`
([`workflows/manager.py`](../../backend/styrmin_backend/workflows/manager.py)) saves one Prefect
deployment per action. Before spec 028 it named each deployment
`<workflow name> (<driver name>@<short commit>)` and tagged it `application/<driver name>`,
`version/<supported versions>`, `hook/<hook>`, `mode/<mode>` and `fingerprint/<short commit>`.
`get_user_action_deployment_id` finds the deployment to run with
`DeploymentFilterTags(all_=...)`, which matches every deployment that has at least these tags, and
picks the newest.

Spec 028 lets an admin load a driver from a driver directory of a repository. Two driver
directories of one repository can hold drivers with the same name. Loaded at the same commit, they
make two driver versions, because `source_path` is part of the identity, and each must run its own
actions (FR-010). Three facts about Prefect 3.8.6 shape the decision (research R-003):

- Prefect replaces a deployment that has the same flow and deployment name, so the second load
  would replace the first driver version's actions.
- Prefect refuses `/`, `%`, `&`, `>` and `<` in deployment names (`BANNED_CHARACTERS`), so a driver
  directory cannot go into the name as it is.
- Prefect's tag filter has `all_`, `any_` and `is_null_`, and no filter that excludes a tag.

## Decision drivers

- Each driver version keeps its own actions, also when another driver version has the same driver
  name and commit (FR-010).
- Driver versions loaded from the repository root keep the deployment names and tags they had, so
  their existing deployments are found without a migration (SC-002).
- Deployment names stay within Prefect's rules.
- No change to Prefect.

## Considered options

1. Tag and name each deployment with the driver version's id.
2. Put the driver directory in the deployment name, with `/` replaced by another character.
3. Refuse a second driver with the same name and commit.
4. Tag the deployment `directory/<driver directory>` and add a digest of the driver directory to
   its name. Leave the names and tags of root driver versions unchanged. A lookup for a root driver
   version drops the deployments that carry a `directory/` tag.

## Decision

We chose option 4.

- **Registration.** When the driver version was loaded from a driver directory,
  `register_user_action` adds the tag `directory/<driver directory>` and appends the first 12 hex
  characters of the SHA-256 of the stored driver directory to the name (`driver_directory_digest`
  in `services/driver/driver_directory.py`): `User Action: setup (infrahub@0123456 c8dc0c0d9f46)`.
  A root driver version keeps `User Action: setup (infrahub@0123456)` and gets no `directory/` tag.
- **Lookup.** `get_user_action_deployment_id` takes `driver_directory` as a keyword argument with
  no default, so every caller states it. With a driver directory, the tag filter includes
  `directory/<driver directory>`. Without one, Styrmin drops every result that carries a
  `directory/` tag before it picks the newest, so a root driver version never runs the action of a
  driver directory version with the same driver name, version and commit.
- **Callers.** `instantiate_application` and the create and upgrade paths of the remediation
  service pass `driver_directory_of(source_type=..., source_path=...)`
  (`services/driver/labels.py`): the `source_path` of a git driver version, and `None` for a local
  one, whose `source_path` is a server path.

The digest only keeps names apart. Lookups use the tag, which carries the readable path.

Option 1 does not work for the load that creates the driver version: the actions are registered
before its row exists. Existing deployments also carry no such tag, so every lookup would need a
second path for them. Option 2 gives `drivers/a-b` and `drivers-a/b` the same name. Option 3
contradicts PRD user story 5, which expects two such driver versions to exist side by side.

## Consequences

- Good, because two driver versions loaded from different driver directories at one commit keep
  separate action deployments, also when their drivers have the same name.
- Good, because driver versions loaded from the repository root keep their deployment names and
  tags, so their deployments resolve as before.
- Good, because the `directory/` tag shows the driver directory of a deployment in the Prefect UI.
- Bad, because the lookup for a root driver version filters Prefect's results in Styrmin: Prefect
  cannot exclude a tag. The result set is small, one deployment per action and driver version
  (research R-010).
- Bad, because the deployment name shows a digest, not the driver directory. To read the driver
  directory of a deployment, read its `directory/` tag.

## Confirmation

- `backend/tests/unit/workflows/test_user_action_registration.py` checks the name and tags with
  and without a driver directory, that two driver directories at one commit register distinct
  deployments, that a lookup with a driver directory filters on its tag, and that a lookup without
  one skips deployments that carry a `directory/` tag.
- `test_drivers_of_one_repository_keep_their_own_actions` in
  `backend/tests/e2e/test_driver_version_reselection.py` loads `drivers/failing-actions` from the
  commit of the session driver's `drivers/simple-app`, and checks that each driver version
  registers its own action deployments with its `directory/` tag and that the session driver's
  deployments stay in place.

## More information

- The pull steps, deployment names and lookup rule are described in
  [hooks-and-actions.md](../knowledge/backend/hooks-and-actions.md#deployment-names).
