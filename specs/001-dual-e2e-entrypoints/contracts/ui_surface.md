# UI Surface Contract

Every `ScenarioDriver` action listed in `scenario_driver.py` MUST be
performable through the product's normal navigation (no hidden routes,
no developer-only query params — SC-006). This document enumerates the
UI surface required to satisfy that contract.

**Legend**:

- **Exists**: the flow ships today on `develop`.
- **Gap**: the flow does not exist and must be added as part of this
  feature (FR-004).
- **Declare**: the action is genuinely not UI-expressible; the
  corresponding scenario is marked `@pytest.mark.api_only(...)` with a
  recorded reason (FR-011). No silent skip.

## Required UI surface

| ScenarioDriver action                  | Reachable from                                                  | Stable anchor the page object targets                      | Status |
| -------------------------------------- | --------------------------------------------------------------- | ---------------------------------------------------------- | ------ |
| `create_cluster`                       | Settings → Clusters → "Create cluster"                          | Dialog role=dialog, form submit button role=button name="Create" | Exists |
| `create_environment`                   | Environments list → "Create environment"                        | Dialog role=dialog name="Create environment"               | Exists |
| `delete_environment`                   | Environment detail → "Delete" action                            | Button role=button name="Delete environment"               | Declare — no existing scenario exercises this; flagged for a follow-up spec. Not a blocker for this feature. |
| `create_backup_storage_location`       | Backup storage locations → "Create"                             | Dialog role=dialog name="Create backup storage location"   | Exists |
| `assign_bsl_to_environment`            | Environment detail → Settings tab → Backup Storage Location selector | Select role=combobox label="Backup Storage Location"  | Exists |
| `load_driver_version`                  | Drivers → "Add driver" → paste git URL + ref                    | Dialog role=dialog name="Add driver"                       | Exists |
| `create_deployment` (basic)            | Environment detail → "Deploy"                                   | Form submit role=button name="Deploy"                      | Exists |
| `create_deployment` (service-name overrides) | Deploy form → "Service name overrides" field array         | Field array under role=group name="Service name overrides" | **Gap** — add field array to `DeployFormPage`, wire to `service_name_overrides` mutation input. |
| `upgrade_deployment`                   | Deployment detail → "Upgrade"                                   | Dialog role=dialog name="Upgrade deployment"               | Exists |
| `get_deployment_timeline`              | Deployment detail → Timeline tab                                | Tab role=tab name="Timeline"; list role=list within panel  | Exists |
| `create_backup`                        | Deployment detail → Backups tab → "Create backup"               | Button role=button name="Create backup"                    | Exists |
| `wait_for_backup` (observe status)     | Backup row status cell                                          | Row status badge identified by `data-testid="backup-status"` plus backup name column | Exists markup, confirm stable anchors during implementation. |
| `create_restore`                       | Deployment detail → Backups tab → row "Restore"                 | Button role=button name="Restore" within row               | Exists |
| `wait_for_restore` (observe status)    | Deployment detail → Restores tab → row status                   | Row status badge `data-testid="restore-status"`            | Exists markup, confirm stable anchors during implementation. |
| `delete_backup`                        | Deployment detail → Backups tab → row "Delete"                  | Confirm dialog role=dialog name="Delete backup"            | Exists |
| `get_backup` (404 after delete)        | Page re-renders without the row                                 | Row absence on Backups tab                                 | Exists |

## Required GraphQL additions (for the gap rows)

None. `service_name_overrides` is already part of the `deploy` mutation
input (`python_sdk/.../deployments.create` already passes it). The gap
is UI-only: surface the field in `DeployFormPage` and forward it to the
existing mutation.

## Stable-anchor conventions (research R4)

Page objects use, in order:

1. `page.get_by_role("<role>", name="<accessible name>")`
2. `page.get_by_label("<label>")`
3. `page.get_by_test_id("<kebab-case id>")` — only where 1 and 2 are
   ambiguous or unstable (repeated rows, icon-only buttons).

New `data-testid` attributes introduced by this feature are listed
above in the "Stable anchor" column and MUST be present in the React
source at merge time.
