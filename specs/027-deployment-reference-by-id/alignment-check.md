# Spec/Ask Alignment Check: Deployment References Stored by Id

**Date**: 2026-10-16

## Source

- PRD "Deployment references stored by id": [opsmill/styrmin#508 (comment 6226052128)](https://github.com/opsmill/styrmin/issues/508#issuecomment-6226052128), fetched with `gh api repos/opsmill/styrmin/issues/comments/6226052128`.
- Seed issue body: [#508](https://github.com/opsmill/styrmin/issues/508).

## Verdict

⚠️ MINOR DRIFT (proceeding)

Every PRD user story, journey, functional requirement, success criterion, edge case, assumption and out-of-scope item is in [spec.md](spec.md), with the same meaning. The differences below come from facts in the code that the PRD did not have, and each is recorded in the spec's Clarifications and in [research.md](research.md). None removes or reverses a PRD requirement.

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
| --- | --- | --- | --- | --- |
| Minor | changed | FR-005 "`createEnvironmentClone` MUST refuse…" | FR-005, Clarifications (planning) | The mutation is `cloneEnvironment` in the code (`api/schema/mutation.py` L1041-1042). Name corrected; behaviour unchanged. |
| Minor | changed | FR-001 "the environment's, the deployment's and the component's config"; P1 journey "in a component's config" | Context, FR-001, US2 scenario 3, R-005 | Operators cannot write a component's scheduling (`ComponentConfigBlock` has no `scheduling` field). A component's terms come from the driver version and are bound when `deploy` and `updateDeploymentVersion` copy them. The requirement applies to those copies. |
| Minor | changed | SC-001 "every later update … succeeds" | SC-001, Edge Cases (driver terms) | Narrowed to terms written by operators. A driver's component definition can only give a name, which is looked up again at each `updateDeploymentVersion` and clone, so after a rename those two writes are refused for driver terms. Reconciles and every other update keep working. Raised by critique X1. |
| Minor | added | Implementation decisions "Environment restore: no change" | FR-006 second bullet, R-009, T035 | The restore's redeploy loop has no savepoint, so one redeploy refused because of a term would drop the other deployments' redeploys. Each redeploy gets a savepoint. Needed for PRD user story 9 ("so that one term does not block a recovery"); it contradicts the PRD's "no change" for the restore module. |
| Minor | added | FR-005 | FR-005, R-007 | The clone check also covers terms in `config_override` (resolved against the source environment), the component definitions of the copied deployments' driver versions, and selected deployments that the clone skips. Each follows from the PRD's FR-005 and FR-008 once the code paths are known. |
| Minor | changed | FR-005 "the clone ends `PARTIAL`" | FR-005, US6 scenario 4 | The clone's status follows the existing derivation: `PARTIAL` when another counterpart is cloned, `FAILED` when none is. The PRD's two-deployment example would derive `FAILED`; the spec's scenario adds a third deployment. |
| Minor | added | Constitution alignment "a public page is out of scope" | FR-012, R-014, T042 | One row and one sentence in the clone section of `docs/docs/concepts-and-architecture/backups-and-restores.md`, which lists the reasons a clone request is refused. A public page about deployment references stays out of scope. Required by Constitution §VII. |
| Minor | added | — | FR-002 first bullet, R-006 | `updateDeployment` saves the request's config before the lookup today, so FR-002's "saves nothing" needs the binding before the save. Behaviour the PRD asked for; the spec records why it is a change. |
| Minor | added | — | R-008 known limit | Inside a cycle of terms, a counterpart created before a peer whose creation fails keeps a term with the peer's id. Not covered by the PRD; recorded as a limit. |

## Action

Proceed. No remediation pass was run. The two items the user may want to confirm before implementation:

- the restore change (savepoint per redeploy), which the PRD listed as "no change";
- the driver-term limit and the narrowed SC-001.
