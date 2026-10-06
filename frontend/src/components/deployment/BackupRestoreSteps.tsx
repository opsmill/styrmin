import { useState } from "react";
import { ChevronRight } from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { StepList, type StepListItem } from "@/components/deployment/StepList";

const FINISHED_STATUSES: ReadonlySet<string> = new Set(["completed", "failed"]);
// Unfinished and failed ones start expanded, so the user can follow or diagnose them.
const EXPANDED_STATUSES: ReadonlySet<string> = new Set([
  "pending",
  "in_progress",
  "failed",
]);

interface BackupRestoreStepsProps {
  parent: "backup" | "restore";
  parentId: string;
  /** Status of the backup or restore, such as `in_progress` or `failed`. */
  status: string;
  steps: StepListItem[];
}

/** The steps of one backup (one per component) or one restore. */
export function BackupRestoreSteps({
  parent,
  parentId,
  status,
  steps,
}: BackupRestoreStepsProps) {
  const normalizedStatus = status.toLowerCase();
  const [open, setOpen] = useState(() =>
    EXPANDED_STATUSES.has(normalizedStatus),
  );
  const parentIdAttribute =
    parent === "backup"
      ? { "data-backup-id": parentId }
      : { "data-restore-id": parentId };

  return (
    <div
      data-testid={`${parent}-steps`}
      data-expanded={open ? "true" : "false"}
      {...parentIdAttribute}
    >
      <Collapsible open={open} onOpenChange={setOpen}>
        <CollapsibleTrigger
          className="flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
          data-testid={`${parent}-steps-trigger`}
        >
          <ChevronRight
            aria-hidden="true"
            className={`h-3 w-3 transition-transform ${open ? "rotate-90" : ""}`}
          />
          Steps ({steps.length})
        </CollapsibleTrigger>
        {/* Kept mounted so the steps of collapsed rows stay in the DOM. */}
        <CollapsibleContent keepMounted>
          <div className="pt-2">
            {steps.length > 0 ? (
              <StepList steps={steps} showTimes />
            ) : (
              <p
                className="text-xs text-muted-foreground"
                data-testid="steps-notice"
              >
                {FINISHED_STATUSES.has(normalizedStatus)
                  ? `No steps recorded for this ${parent}.`
                  : "Waiting for the first step."}
              </p>
            )}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}
