# Spec/PRD Alignment Check: helm-controller Runs with Helm v4 Defaults

## Source

- PRD "Run helm-controller with Helm v4 defaults": [opsmill/styrmin#435 (comment)](https://github.com/opsmill/styrmin/issues/435#issuecomment-6210811102), fetched with `gh api repos/opsmill/styrmin/issues/comments/6210811102` on 2026-10-16.
- Seed issue: [#435](https://github.com/opsmill/styrmin/issues/435).

## Verdict

⚠️ MINOR DRIFT (proceeding)

Every PRD goal, user story, functional requirement, success criterion, decision, testing decision, documentation item and out-of-scope item is in [spec.md](spec.md). The differences come from the planning research, which answered the PRD's open questions from helm-controller v1.6.5 and Helm v4.2.4 source ([research.md](research.md)). Each one serves a goal the PRD states. The first finding adds a production code change that the PRD's module list does not name, so the reviewer should look at it.

## Findings

| Severity | Category | PRD reference | Spec reference | Description |
| --- | --- | --- | --- | --- |
| Minor | added | "Edge cases": "Styrmin's labels reach every resource, because the label patch targets every name"; "Implementation decisions", Modules | FR-013, SC-006, Story 2 scenario 3, Clarifications (planning session) | Research R-008 found that the label patch, a JSON patch `add` under `/metadata/labels/`, fails the whole render on a resource without `metadata.labels`. Helm hooks reach that patch once the gate is gone. The spec adds FR-013: Styrmin's labels reach a resource without labels without a render error. The plan makes the every-resource label patch a strategic merge (D-006), a change to the post-render patch code that the PRD's module list does not name. Without it, the PRD's own statement that labels reach every resource is false for unlabelled hooks. A driver that works today could also fail after the agent upgrade, against user needs 4 and 7. |
| Minor | changed | User story 6 and the "Creating a driver" documentation item: "an action which changes a resource the chart owns can make the next upgrade fail" | FR-007, Story 4 scenario 1, user need 6 (annotated), Edge Cases | The PRD wrote this while it was not known whether helm-controller forces conflicts. Research R-002 shows it always does, so the upgrade does not fail; the changed field returns to the chart's value. The spec keeps the PRD's need verbatim with a note, and the documentation states what happens (Constitution §VII). |
| Minor | changed | FR-003 verification: "checks the node selector and tolerations of a Helm hook Job's pod"; SC-004: "runs on those nodes" | FR-003, SC-004, Clarifications (planning session) | Styrmin's scheduling settings have no node selector; nodes are chosen with node affinity and tolerations (R-009). The E2E vcluster has one node. The check covers tolerations, node affinity and the other scheduling fields, and that the hook Job completed. It does not check placement on a second node. |
| Minor | added | "Modules": `simple-app` test chart adds a pre-upgrade Helm hook Job | plan D-002, contract C-005 | The same chart value also renders an unlabelled pre-upgrade hook ConfigMap. This checks FR-013 end to end, as Constitution §V requires (critique X1). The PRD's limit holds: the value is off by default, and only the scheduling test turns it on, through a test-only driver. |
| Minor | changed | "Not decided": whether to add E2E checks for `Stalled` and the readiness timeout | Clarifications (2026-10-16), Story 1 scenarios 4 and 5 | The PRD left this open. The spec answers it provisionally: unit tests with recorded FluxCD states cover these two outcomes. It flags the decision for the maintainer, as AGENTS.md asks. tasks.md T034 carries the question into the pull request. |
| Minor | added | "Success criteria" SC-001 to SC-004 | SC-005, SC-006 | SC-005 restates the PRD's "successful change" acceptance ("the deployment reaches `Running`") as a criterion. SC-006 is the success criterion of FR-013. |
| None | structural | "User journey P1", "There is no P2" | User Stories 1 to 4, all P1 | The spec splits the PRD's single P1 journey into four P1 stories so that each can be checked on its own. It adds no P2 and no E2E test of the agent upgrade. |

No PRD requirement, goal, non-goal or acceptance criterion is missing, dropped or softened, and nothing in the spec contradicts a PRD constraint.

## Action

Proceed. No remediation pass was run (0 of 2 used). The reviewer should confirm the label patch change (first finding) and the `Stalled` and readiness timeout coverage decision (fifth finding) when they read the pull request.
