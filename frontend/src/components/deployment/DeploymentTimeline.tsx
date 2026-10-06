import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { StatusBadge } from "@/components/StatusBadge";
import { ContextDiffView } from "@/components/deployment/ContextDiffView";
import { StepList, type StepListItem } from "@/components/deployment/StepList";
import { ChevronRight, Clock, History } from "lucide-react";

const TASK_TYPE_LABELS: Record<string, string> = {
  create_instance: "Create",
  update_instance: "Update",
  upgrade_instance: "Upgrade",
  delete_instance: "Delete",
  delete_deployment: "Delete",
  stop_components: "Stop Components",
  start_components: "Start Components",
  run_job: "Run Job",
  noop: "No-op",
};

// Task.status values after which no new step starts.
const FINISHED_TASK_STATUSES = new Set(["success", "failed"]);

function formatTimestamp(value: string | null | undefined): string {
  if (!value) return "N/A";
  return new Date(value).toLocaleString();
}

interface TimelineTask {
  id: string;
  type: string;
  status: string;
  message?: string | null;
  createdOn?: string | null;
  updatedOn?: string | null;
  startedByStepId?: string | null;
  steps: StepListItem[];
}

interface ContextChange {
  path: string;
  action: string;
  oldValue?: unknown;
  newValue?: unknown;
}

interface ContextDiffData {
  changes: ContextChange[];
}

export interface TimelineEntry {
  task: TimelineTask;
  applicationVersion?: string | null;
  contextDiff?: ContextDiffData | null;
}

interface DeploymentTimelineProps {
  entries: TimelineEntry[];
}

export function DeploymentTimeline({ entries }: DeploymentTimelineProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <History className="h-4 w-4" />
          History
        </CardTitle>
      </CardHeader>
      <CardContent>
        {entries.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No operations have been recorded for this deployment.
          </p>
        ) : (
          <div className="space-y-0 divide-y">
            {entries.map((entry) => (
              <TimelineEntryRow key={entry.task.id} entry={entry} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function TaskSteps({ task }: { task: TimelineTask }) {
  if (task.steps.length > 0) {
    return <StepList steps={task.steps} />;
  }
  const finished = FINISHED_TASK_STATUSES.has(task.status.toLowerCase());
  return (
    <p className="text-xs text-muted-foreground" data-testid="steps-notice">
      {finished
        ? "No steps recorded for this task."
        : "Waiting for the first step."}
    </p>
  );
}

function TimelineEntryRow({ entry }: { entry: TimelineEntry }) {
  const { task, applicationVersion, contextDiff } = entry;
  const typeLabel = TASK_TYPE_LABELS[task.type] ?? task.type;
  const hasChanges = contextDiff != null && contextDiff.changes.length > 0;
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div
      className="py-3 first:pt-0 last:pb-0"
      data-testid="timeline-entry"
      data-task-id={task.id}
      data-task-type={task.type}
      data-task-status={task.status}
      data-created-on={task.createdOn ?? ""}
      data-application-version={applicationVersion ?? ""}
      data-started-by-step-id={task.startedByStepId ?? ""}
      data-expanded={isOpen ? "true" : "false"}
    >
      <Collapsible open={isOpen} onOpenChange={setIsOpen}>
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex w-full cursor-pointer items-center justify-between gap-2 text-left"
          >
            <span className="flex items-center gap-2">
              <ChevronRight
                aria-hidden="true"
                className={`h-3 w-3 shrink-0 transition-transform ${isOpen ? "rotate-90" : ""}`}
              />
              <Badge variant="outline">{typeLabel}</Badge>
              <StatusBadge status={task.status.toUpperCase()} />
              {applicationVersion && (
                <span className="text-xs font-mono text-muted-foreground">
                  v{applicationVersion}
                </span>
              )}
            </span>
            <span className="flex items-center gap-1 text-xs text-muted-foreground">
              <Clock aria-hidden="true" className="h-3 w-3" />
              <span>{formatTimestamp(task.createdOn)}</span>
            </span>
          </button>
        </CollapsibleTrigger>
        {task.message && (
          <p className="mt-1 pl-5 text-xs text-muted-foreground">
            {task.message}
          </p>
        )}
        {/* Kept mounted so the steps of collapsed entries stay in the DOM. */}
        <CollapsibleContent keepMounted>
          <div className="flex flex-col gap-3 pt-3 pl-5">
            <TaskSteps task={task} />
            {hasChanges && <ContextDiffView changes={contextDiff.changes} />}
          </div>
        </CollapsibleContent>
      </Collapsible>
    </div>
  );
}
