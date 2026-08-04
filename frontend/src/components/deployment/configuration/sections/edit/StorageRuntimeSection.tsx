// Section components bind to arbitrary dotted sub-paths under
// `UpdateDeploymentInput`; the TanStack Form per-path generic narrowing is
// not usable across the full schema, so `form.Field` children are typed as
// `any` and validated through the field's own validator.
/* eslint-disable @typescript-eslint/no-explicit-any */
import type { UpdateDeploymentInput } from "@/generated/graphql";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { DEFAULT_BACKUP_TTL, validateBackupTtl } from "@/lib/backup-ttl";
import type { SectionId } from "@/lib/configuration-types";

import { ChangedFieldFrame } from "../../ChangedFieldFrame";
import { useDrawerDiff } from "../../DrawerDiffContext";
import type { ReactFormLike } from "./types";

interface Props {
  form: ReactFormLike;
  initial: UpdateDeploymentInput;
  environment: UpdateDeploymentInput;
  anchorId: SectionId;
}

/**
 * Storage & Runtime section of the edit drawer.
 *
 * Editable fields:
 *  - `backupTtl` — the deployment's own backup retention policy (016).
 *
 * Scope note: `dbSize`, `standardStorage.storageClass`, and `nodeSelector`
 * are deliberately **not** editable here. They remain read-only on the
 * Settings tab (see `StorageRuntimeSummary`), which is the state
 * 011-unified-deployment-config left them in; re-opening them is a product
 * decision, not a side effect of shipping retention. The section header says
 * as much so an operator does not hunt for fields that are not here.
 *
 * Clearing the input submits `undefined`, which drops the key from the
 * full-replacement `UpdateDeploymentInput` — the documented gesture for
 * "this deployment sets no policy, inherit the shallower scope". Sending
 * `""` would fail backend validation, and `null` is not distinguishable
 * from omitted on this surface.
 */
export function StorageRuntimeSection({
  form,
  initial,
  environment,
  anchorId,
}: Props) {
  const changedCount = useDrawerDiff().entries.filter(
    (e) => e.section === anchorId,
  ).length;

  // Which scope the operator would fall back to if they cleared the field.
  const inheritedTtl = environment.backupTtl ?? null;

  return (
    <section
      data-section={anchorId}
      id={`${anchorId}-anchor`}
      className="scroll-mt-4"
    >
      <div className="mb-3 flex items-center gap-3">
        <h3
          id={`${anchorId}-heading`}
          className="text-sm font-semibold uppercase tracking-wide text-foreground"
        >
          Storage &amp; Runtime
        </h3>
        {changedCount > 0 && (
          <span
            data-testid={`section-changed-chip-${anchorId}`}
            className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-900 dark:bg-amber-950/40 dark:text-amber-300"
          >
            {changedCount} changed
          </span>
        )}
      </div>

      <div className="space-y-4">
        <form.Field
          name="backupTtl"
          validators={{
            // The shared validator from `lib/backup-ttl.ts`, so this field
            // cannot drift from the backend rule or from the environment-scope
            // form. Blank is not invalid — it is how the policy is cleared.
            onChange: ({ value }: { value: unknown }) => {
              if (value === undefined || value === null || value === "") {
                return undefined;
              }
              return validateBackupTtl(String(value)) ?? undefined;
            },
          }}
        >
          {(field: any) => (
            <ChangedFieldFrame
              name="backupTtl"
              form={form}
              initial={initial.backupTtl}
              environment={environment.backupTtl}
            >
              <div className="space-y-1">
                <Label htmlFor="storage-backup-ttl">Backup retention TTL</Label>
                <Input
                  id="storage-backup-ttl"
                  data-testid="storage-backup-ttl-input"
                  value={(field.state.value as string | undefined) ?? ""}
                  onChange={(e) =>
                    field.handleChange(
                      e.target.value === "" ? undefined : e.target.value,
                    )
                  }
                  onBlur={field.handleBlur}
                  placeholder={`e.g. ${DEFAULT_BACKUP_TTL}`}
                  autoComplete="off"
                />
                {field.state.meta.errors.length > 0 && (
                  <p
                    data-testid="storage-backup-ttl-error"
                    className="text-xs text-destructive"
                  >
                    {String(field.state.meta.errors[0])}
                  </p>
                )}
                <p
                  data-testid="storage-backup-ttl-hint"
                  className="text-xs text-muted-foreground"
                >
                  How long this deployment&apos;s backups are kept, as a Go
                  duration using h/m/s units. Clear the field to inherit{" "}
                  {inheritedTtl
                    ? `the environment's ${inheritedTtl}`
                    : `the shallower scope (default ${DEFAULT_BACKUP_TTL})`}
                  . Changing it affects future backups only — backups already
                  created keep the expiration set when they were made.
                </p>
              </div>
            </ChangedFieldFrame>
          )}
        </form.Field>

        <p className="text-xs italic text-muted-foreground">
          Database size, storage class, and node selector are shown read-only on
          the Settings tab.
        </p>
      </div>
    </section>
  );
}
