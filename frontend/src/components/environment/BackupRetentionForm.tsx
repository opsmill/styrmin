/**
 * BackupRetentionForm — environment-scope backup retention editor
 * (016-backup-retention-ttl).
 *
 * A single text input holding the environment's ``backup_ttl`` — the
 * duration Velero keeps backups taken for deployments in this
 * environment. Validation mirrors the backend rule via
 * ``@/lib/backup-ttl``; inline error below the input, Save disabled while
 * the value is invalid.
 *
 * A blank input means "no policy at this scope": the form submits
 * ``null``, and resolution falls through to the cluster scope and then to
 * the built-in ``720h`` (deepest scope wins). That is how an operator
 * reverts to the default, so the empty case is spelled out in the hint
 * text rather than left to be discovered.
 *
 * Conventions follow the sibling ``EnvVarsForm``: Save is role-gated
 * behind ``READ_WRITE``, opens the shared ``RedeployConfirmDialog`` naming
 * the deployments about to be redeployed, and flips to "Saving..." while a
 * submission is in flight. Submit failures keep the edited value and
 * surface an error notice.
 */
import { useMemo, useState } from "react";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { IfRole } from "@/auth/IfRole";
import { DEFAULT_BACKUP_TTL, validateBackupTtl } from "@/lib/backup-ttl";

import { RedeployConfirmDialog } from "./RedeployConfirmDialog";

export interface BackupRetentionFormDeployment {
  id: string;
  name: string;
}

export interface BackupRetentionFormProps {
  /** The persisted ``backup_ttl``, or ``null`` when this scope sets none. */
  initialBackupTtl: string | null;
  deployments: BackupRetentionFormDeployment[];
  /**
   * Persist the new policy. ``null`` clears it (a blank input), which
   * hands resolution back to the shallower scopes.
   */
  onSubmit: (backupTtl: string | null) => Promise<void>;
  /** Optional error string from a prior submission. */
  submitError?: string | null;
  /** Hint that a submission is in flight (disables the Save button). */
  isSubmitting?: boolean;
  /**
   * When set, the form renders a warning Alert and disables Save. Supplied
   * by the parent section when the persisted environment config carries
   * ``dedicated_ingress`` or ``scheduling`` overrides — nested fields the
   * v1 form cannot map, which a full-replacement ``updateEnvironment``
   * would silently clear. Same gate as ``EnvVarsForm``; see ADR-012
   * §"Decision 2 — Full-replacement input".
   */
  blockedReason?: string | null;
}

const INPUT_ID = "backup-retention-ttl";

export function BackupRetentionForm({
  initialBackupTtl,
  deployments,
  onSubmit,
  submitError,
  isSubmitting = false,
  blockedReason = null,
}: BackupRetentionFormProps) {
  const [value, setValue] = useState<string>(initialBackupTtl ?? "");
  const [confirmOpen, setConfirmOpen] = useState(false);

  // A blank input is the "clear the policy" gesture, not a value: it
  // submits ``null`` and never reaches the validator (which rejects "" as
  // the backend does).
  const isBlank = value.trim() === "";
  const error = useMemo(
    () => (isBlank ? null : validateBackupTtl(value)),
    [isBlank, value],
  );

  const handleSaveClick = () => {
    if (error || isSubmitting || blockedReason) return;
    setConfirmOpen(true);
  };

  const handleConfirmRedeploy = async () => {
    setConfirmOpen(false);
    try {
      await onSubmit(isBlank ? null : value);
    } catch {
      // The parent section owns error presentation: it catches the failure,
      // feeds it back as ``submitError``, and rethrows so its own callers
      // can observe it. Swallow the rethrow here so a failed save does not
      // escape the click handler as an unhandled promise rejection. The
      // edited value stays in state, so the operator can retry.
    }
  };

  const handleCancelRedeploy = () => {
    setConfirmOpen(false);
  };

  return (
    <div className="flex flex-col gap-3" data-testid="backup-retention-form">
      {blockedReason && (
        <Alert
          variant="destructive"
          data-testid="backup-retention-blocked-warning"
        >
          <AlertTitle>Save disabled — nested overrides present</AlertTitle>
          <AlertDescription>{blockedReason}</AlertDescription>
        </Alert>
      )}

      {submitError && (
        <Alert
          variant="destructive"
          data-testid="backup-retention-submit-error"
        >
          <AlertTitle>Update failed</AlertTitle>
          <AlertDescription>{submitError}</AlertDescription>
        </Alert>
      )}

      <div className="flex flex-col gap-1">
        <Label htmlFor={INPUT_ID}>Retention (backup_ttl)</Label>
        <Input
          id={INPUT_ID}
          className="max-w-xs"
          placeholder={DEFAULT_BACKUP_TTL}
          value={value}
          onChange={(e) => setValue(e.target.value)}
          aria-invalid={error ? true : undefined}
          aria-describedby={
            error ? "backup-retention-error-text" : "backup-retention-hint"
          }
          data-testid="backup-retention-input"
        />
        {error ? (
          <p
            id="backup-retention-error-text"
            className="text-xs text-destructive"
            data-testid="backup-retention-error"
          >
            {error}
          </p>
        ) : (
          <p
            id="backup-retention-hint"
            className="text-xs text-muted-foreground"
            data-testid="backup-retention-hint"
          >
            Go duration in h/m/s units — {DEFAULT_BACKUP_TTL} (30 days), 2160h
            (90 days), 1h30m. Leave empty to clear the environment policy. A
            change applies to backups created from now on, not to existing ones.
          </p>
        )}
      </div>

      <div className="flex items-center justify-between gap-3 pt-2">
        <span
          className="text-xs text-muted-foreground"
          data-testid="backup-retention-current"
        >
          {initialBackupTtl === null
            ? `No environment policy set — backups use the cluster policy, or the built-in ${DEFAULT_BACKUP_TTL}.`
            : `Environment policy: ${initialBackupTtl}`}
        </span>
        <IfRole minimum="READ_WRITE">
          <Button
            type="button"
            onClick={handleSaveClick}
            disabled={Boolean(error) || isSubmitting || Boolean(blockedReason)}
            data-testid="backup-retention-save-button"
          >
            {isSubmitting ? "Saving..." : "Save"}
          </Button>
        </IfRole>
      </div>

      <RedeployConfirmDialog
        open={confirmOpen}
        deploymentCount={deployments.length}
        deploymentNames={deployments.map((d) => d.name)}
        onConfirm={handleConfirmRedeploy}
        onCancel={handleCancelRedeploy}
      />
    </div>
  );
}
