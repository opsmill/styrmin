/**
 * RedeployConfirmDialog — pre-fanout confirmation dialog (009 / US4).
 *
 * Always shown on Save, including the zero-deployment case. Renders the
 * count plus the deployment names, truncated past five with an
 * "and N more" tail.
 */
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

const MAX_DISPLAYED_NAMES = 5;

export interface RedeployConfirmDialogProps {
  open: boolean;
  deploymentCount: number;
  deploymentNames: string[];
  onConfirm: () => void;
  onCancel: () => void;
}

function buildBody(count: number, names: string[]): string {
  if (count === 0) {
    return "No deployments will be redeployed.";
  }
  if (count === 1) {
    return `1 deployment will be redeployed: ${names[0]}.`;
  }
  if (count <= MAX_DISPLAYED_NAMES) {
    return `${count} deployments will be redeployed: ${names.join(", ")}.`;
  }
  const head = names.slice(0, MAX_DISPLAYED_NAMES).join(", ");
  const remaining = count - MAX_DISPLAYED_NAMES;
  return `${count} deployments will be redeployed: ${head}, and ${remaining} more.`;
}

export function RedeployConfirmDialog({
  open,
  deploymentCount,
  deploymentNames,
  onConfirm,
  onCancel,
}: RedeployConfirmDialogProps) {
  const body = buildBody(deploymentCount, deploymentNames);
  const handleOpenChange = (next: boolean) => {
    if (!next) onCancel();
  };
  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent data-testid="redeploy-confirm-dialog">
        <DialogHeader>
          <DialogTitle>Confirm environment update</DialogTitle>
          <DialogDescription data-testid="redeploy-confirm-dialog-body">
            {body}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            onClick={onCancel}
            data-testid="redeploy-confirm-cancel"
          >
            Cancel
          </Button>
          <Button
            type="button"
            onClick={onConfirm}
            data-testid="redeploy-confirm-redeploy"
          >
            Redeploy
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
