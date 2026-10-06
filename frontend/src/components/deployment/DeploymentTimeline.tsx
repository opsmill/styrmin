import { useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { ContextDiffView } from "@/components/deployment/ContextDiffView";
import {
  StepList,
  type LinkedTask,
  type StartedTask,
  type StepListItem,
} from "@/components/deployment/StepList";
import { TaskLink } from "@/components/deployment/TaskLink";
import { TaskResultBadge } from "@/components/deployment/TaskResultBadge";
import {
  TimelineLinksContext,
  timelineEntryAnchorId,
  type TimelineLinks,
} from "@/components/deployment/timeline-links";
import type { TaskResult } from "@/generated/graphql";
import { taskTypeLabel } from "@/lib/task-display";
import { ChevronRight, Clock, History } from "lucide-react";

// Task.status values after which no new step starts.
const FINISHED_TASK_STATUSES = new Set(["success", "failed"]);

// Entries with these results start expanded, so a running task can be followed.
const EXPANDED_RESULTS: ReadonlySet<TaskResult> = new Set([
  "RUNNING",
  "FAILED",
]);

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
  result: TaskResult;
  startedByStepId?: string | null;
  startedBy?: LinkedTask | null;
  startedTasks?: StartedTask[];
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
  // Kept here, by task id, so a link can expand another entry.
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  // An entry keeps its first state after a refresh, so it does not collapse when it finishes.
  const unseen = entries.filter((entry) => !(entry.task.id in expanded));
  if (unseen.length > 0) {
    setExpanded((current) => {
      const next = { ...current };
      for (const { task } of unseen) {
        next[task.id] ??= EXPANDED_RESULTS.has(task.result);
      }
      return next;
    });
  }
  const [linkTarget, setLinkTarget] = useState<{
    taskId: string;
    seq: number;
  } | null>(null);

  const links = useMemo<TimelineLinks>(() => {
    const taskIds = new Set(entries.map((entry) => entry.task.id));
    return {
      hasTask: (taskId) => taskIds.has(taskId),
      showTask: (taskId) => {
        setExpanded((current) => ({ ...current, [taskId]: true }));
        setLinkTarget((current) => ({
          taskId,
          seq: (current?.seq ?? 0) + 1,
        }));
      },
    };
  }, [entries]);

  // Runs after the target entry rendered expanded; `seq` repeats a click on the same link.
  useEffect(() => {
    if (linkTarget == null) return;
    const element = document.getElementById(
      timelineEntryAnchorId(linkTarget.taskId),
    );
    if (element == null) return;
    element
      .querySelector<HTMLElement>("[data-testid=timeline-entry-trigger]")
      ?.focus({ preventScroll: true });
    element.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [linkTarget]);

  return (
    <TimelineLinksContext.Provider value={links}>
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
                <TimelineEntryRow
                  key={entry.task.id}
                  entry={entry}
                  isOpen={expanded[entry.task.id] ?? false}
                  onOpenChange={(open) =>
                    setExpanded((current) => ({
                      ...current,
                      [entry.task.id]: open,
                    }))
                  }
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </TimelineLinksContext.Provider>
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

interface TimelineEntryRowProps {
  entry: TimelineEntry;
  isOpen: boolean;
  onOpenChange: (open: boolean) => void;
}

function TimelineEntryRow({
  entry,
  isOpen,
  onOpenChange,
}: TimelineEntryRowProps) {
  const { task, applicationVersion, contextDiff } = entry;
  const typeLabel = taskTypeLabel(task.type);
  const hasChanges = contextDiff != null && contextDiff.changes.length > 0;

  return (
    <div
      id={timelineEntryAnchorId(task.id)}
      className="scroll-mt-4 py-3 first:pt-0 last:pb-0"
      data-testid="timeline-entry"
      data-task-id={task.id}
      data-task-type={task.type}
      data-task-status={task.status}
      data-task-result={task.result}
      data-created-on={task.createdOn ?? ""}
      data-application-version={applicationVersion ?? ""}
      data-started-by-step-id={task.startedByStepId ?? ""}
      data-started-by-task-id={task.startedBy?.id ?? ""}
      data-started-by-task-type={task.startedBy?.type ?? ""}
      data-expanded={isOpen ? "true" : "false"}
    >
      <Collapsible open={isOpen} onOpenChange={onOpenChange}>
        <CollapsibleTrigger asChild>
          <button
            type="button"
            className="flex w-full cursor-pointer items-center justify-between gap-2 text-left"
            data-testid="timeline-entry-trigger"
          >
            <span className="flex items-center gap-2">
              <ChevronRight
                aria-hidden="true"
                className={`h-3 w-3 shrink-0 transition-transform ${isOpen ? "rotate-90" : ""}`}
              />
              <Badge variant="outline">{typeLabel}</Badge>
              <TaskResultBadge result={task.result} />
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
        {task.startedBy && (
          <p
            className="mt-1 pl-5 text-xs text-muted-foreground"
            data-testid="started-by"
          >
            <TaskLink taskId={task.startedBy.id}>
              Started by {taskTypeLabel(task.startedBy.type)}
            </TaskLink>
          </p>
        )}
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
