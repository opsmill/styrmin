import { useEffect, useState } from "react";
import {
  Circle,
  CircleCheck,
  CircleSlash,
  CircleX,
  LoaderCircle,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { TaskLink } from "@/components/deployment/TaskLink";
import { TaskResultBadge } from "@/components/deployment/TaskResultBadge";
import {
  useGetStepOutputQuery,
  type StepKind,
  type StepStatus,
  type TaskResult,
} from "@/generated/graphql";
import { taskTypeLabel } from "@/lib/task-display";
import { cn } from "@/lib/utils";

export interface StepErrorItem {
  attempt: number;
  message: string;
  occurredAt?: string | null;
}

/** Another task that a step or a task links to. */
export interface LinkedTask {
  id: string;
  type: string;
}

export interface StartedTask extends LinkedTask {
  result: TaskResult;
}

export interface StepListItem {
  id: string;
  key: string;
  name: string;
  kind: StepKind;
  status: StepStatus;
  startedAt?: string | null;
  endedAt?: string | null;
  durationSeconds?: number | null;
  attemptCount: number;
  errors?: StepErrorItem[];
  detail?: string | null;
  rolledBackAt?: string | null;
  rollbackMessage?: string | null;
  hasOutput?: boolean;
  outputTruncated?: boolean;
  supersededBy?: LinkedTask | null;
  startedTasks?: StartedTask[];
  /** Set while a running operator-phase step has had no agent report for over 60 seconds. */
  noReportSince?: string | null;
}

interface StepStatusConfig {
  label: string;
  icon: LucideIcon;
  className: string;
}

// Every status has a text label, so status is never shown by colour alone.
const STEP_STATUS: Record<StepStatus, StepStatusConfig> = {
  PENDING: {
    label: "Pending",
    icon: Circle,
    className: "text-muted-foreground",
  },
  RUNNING: {
    label: "Running",
    icon: LoaderCircle,
    className: "text-warning",
  },
  SUCCEEDED: {
    label: "Succeeded",
    icon: CircleCheck,
    className: "text-success",
  },
  FAILED: { label: "Failed", icon: CircleX, className: "text-destructive" },
  SUPERSEDED: {
    label: "Superseded",
    icon: CircleSlash,
    className: "text-muted-foreground",
  },
};

function formatDuration(totalSeconds: number): string {
  if (totalSeconds < 1) return "<1s";
  const seconds = Math.floor(totalSeconds);
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  const pad = (value: number) => String(value).padStart(2, "0");
  if (hours > 0) return `${hours}h ${pad(minutes)}m`;
  if (minutes > 0) return `${minutes}m ${pad(rest)}s`;
  return `${rest}s`;
}

function formatTimestamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function useNow(intervalMs: number): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

// Ticks on its own, so only running rows re-render every second.
function RunningFor({ startedAt }: { startedAt: string }) {
  const now = useNow(1_000);
  const started = new Date(startedAt).getTime();
  if (Number.isNaN(started)) return null;
  const elapsed = Math.max(0, (now.getTime() - started) / 1_000);
  return <>running for {formatDuration(elapsed)}</>;
}

// Newest error first: the latest attempt is the likely cause.
function StepErrors({ errors }: { errors: StepErrorItem[] }) {
  return (
    <ol className="flex flex-col gap-1.5" data-testid="step-errors">
      {[...errors].reverse().map((error, index) => (
        <li
          key={`${error.attempt}-${index}`}
          className="border-l-2 border-destructive/60 pl-2"
          data-testid="step-error"
          data-attempt={error.attempt}
          data-occurred-at={error.occurredAt ?? ""}
        >
          <p className="text-xs text-muted-foreground">
            Attempt {error.attempt} failed
            {error.occurredAt ? ` at ${formatTimestamp(error.occurredAt)}` : ""}
          </p>
          <p
            className="whitespace-pre-wrap break-words text-xs text-foreground"
            data-testid="step-error-message"
          >
            {error.message}
          </p>
        </li>
      ))}
    </ol>
  );
}

// Fetched only on demand: output can be long, so the timeline query leaves it out.
function StepOutput({ stepId }: { stepId: string }) {
  const [open, setOpen] = useState(false);
  const { data, isLoading, error } = useGetStepOutputQuery(
    { stepId },
    { enabled: open },
  );
  const output = data?.step?.output;

  return (
    <div className="flex flex-col gap-1.5">
      <Button
        type="button"
        variant="link"
        size="sm"
        className="h-auto self-start px-0"
        aria-expanded={open}
        data-testid="show-output"
        onClick={() => setOpen((value) => !value)}
      >
        {open ? "Hide output" : "Show output"}
      </Button>
      {open &&
        (isLoading ? (
          <p className="text-xs text-muted-foreground">Loading output…</p>
        ) : error ? (
          <p className="text-xs text-destructive" role="alert">
            The output could not be loaded: {error.message}
          </p>
        ) : output ? (
          <>
            {data?.step?.outputTruncated && (
              <p
                className="text-xs text-muted-foreground"
                data-testid="output-truncated"
              >
                Earlier output was cut
              </p>
            )}
            <pre
              className="max-h-80 overflow-auto rounded-md border bg-muted p-2 font-mono text-xs whitespace-pre"
              data-testid="step-output"
            >
              {output}
            </pre>
          </>
        ) : (
          <p className="text-xs text-muted-foreground">
            No output was recorded for this step.
          </p>
        ))}
    </div>
  );
}

function StepFailureDetails({ step }: { step: StepListItem }) {
  const errors = step.errors ?? [];
  if (
    errors.length === 0 &&
    !step.detail &&
    !step.rolledBackAt &&
    !step.hasOutput
  ) {
    return null;
  }
  return (
    <div className="flex flex-col gap-2 sm:pl-31">
      {errors.length > 0 && <StepErrors errors={errors} />}
      {step.detail && (
        <p className="text-xs">
          <span className="font-medium text-muted-foreground">FluxCD: </span>
          <span
            className="whitespace-pre-wrap break-words"
            data-testid="step-detail"
          >
            {step.detail}
          </span>
        </p>
      )}
      {step.rolledBackAt && (
        <p
          className="text-xs text-foreground"
          data-testid="step-rollback"
          data-rolled-back-at={step.rolledBackAt}
        >
          FluxCD rolled back the release at {formatTimestamp(step.rolledBackAt)}
          {step.rollbackMessage ? `: ${step.rollbackMessage}` : ""}
        </p>
      )}
      {step.hasOutput && <StepOutput stepId={step.id} />}
    </div>
  );
}

// The tasks a hook step started, each with its result and a link to its entry.
function StartedTasks({ tasks }: { tasks: StartedTask[] }) {
  return (
    <div className="flex flex-col gap-1 sm:pl-31">
      <p className="text-xs text-muted-foreground">Started tasks</p>
      <ul
        className="flex flex-col gap-1"
        aria-label="Started tasks"
        data-testid="started-tasks"
      >
        {tasks.map((task) => (
          <li
            key={task.id}
            className="flex flex-wrap items-center gap-2 text-xs"
            data-testid="started-task"
            data-task-id={task.id}
            data-task-type={task.type}
            data-task-result={task.result}
          >
            <TaskLink taskId={task.id}>{taskTypeLabel(task.type)}</TaskLink>
            <TaskResultBadge result={task.result} />
          </li>
        ))}
      </ul>
    </div>
  );
}

// Shown for backups and restores, whose users read when each part ran.
function StepTimes({ step }: { step: StepListItem }) {
  if (!step.startedAt) return null;
  return (
    <p
      className="text-xs tabular-nums text-muted-foreground sm:pl-31"
      data-testid="step-times"
    >
      Started {formatTimestamp(step.startedAt)}
      {step.endedAt ? `, ended ${formatTimestamp(step.endedAt)}` : ""}
    </p>
  );
}

function StepRow({
  step,
  showTimes,
}: {
  step: StepListItem;
  showTimes: boolean;
}) {
  const status = STEP_STATUS[step.status] ?? {
    label: step.status,
    icon: Circle,
    className: "text-muted-foreground",
  };
  const Icon = status.icon;
  const timing =
    step.status === "RUNNING" && step.startedAt ? (
      <RunningFor startedAt={step.startedAt} />
    ) : step.durationSeconds != null ? (
      formatDuration(step.durationSeconds)
    ) : null;

  return (
    <li
      className="flex flex-col gap-2 px-3 py-2 text-sm"
      data-testid="step-row"
      data-step-id={step.id}
      data-step-key={step.key}
      data-step-kind={step.kind}
      data-step-status={step.status}
      data-step-started-at={step.startedAt ?? ""}
      data-step-ended-at={step.endedAt ?? ""}
      data-step-attempts={step.attemptCount}
      data-step-has-output={step.hasOutput ? "true" : "false"}
      data-superseded-by-task-id={step.supersededBy?.id ?? ""}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span
          className={cn(
            "flex w-28 shrink-0 items-center gap-1.5 text-xs font-medium",
            status.className,
          )}
          data-testid="step-status"
        >
          <Icon
            aria-hidden="true"
            className={cn(
              "h-3.5 w-3.5 shrink-0",
              step.status === "RUNNING" && "animate-spin",
            )}
          />
          {status.label}
        </span>
        <span
          className="min-w-0 flex-1 break-words text-foreground"
          data-testid="step-name"
        >
          {step.name}
        </span>
        {step.attemptCount > 1 && (
          <span
            className="text-xs text-muted-foreground"
            data-testid="step-attempts"
          >
            {step.attemptCount} attempts
          </span>
        )}
        {timing != null && (
          <span
            className="text-xs tabular-nums text-muted-foreground"
            data-testid="step-duration"
          >
            {timing}
          </span>
        )}
      </div>
      {showTimes && <StepTimes step={step} />}
      {step.noReportSince && (
        <p
          className="flex items-center gap-1.5 text-xs text-foreground sm:pl-31"
          data-testid="step-no-report"
          data-no-report-since={step.noReportSince}
        >
          <TriangleAlert
            aria-hidden="true"
            className="h-3.5 w-3.5 shrink-0 text-warning"
          />
          No report from the agent since {formatTimestamp(step.noReportSince)}
        </p>
      )}
      {step.supersededBy && (
        <p
          className="text-xs text-muted-foreground sm:pl-31"
          data-testid="step-superseded-by"
          data-superseded-by-task-id={step.supersededBy.id}
          data-superseded-by-task-type={step.supersededBy.type}
        >
          <TaskLink taskId={step.supersededBy.id}>
            Superseded by {taskTypeLabel(step.supersededBy.type)}
          </TaskLink>
        </p>
      )}
      <StepFailureDetails step={step} />
      {step.startedTasks && step.startedTasks.length > 0 && (
        <StartedTasks tasks={step.startedTasks} />
      )}
    </li>
  );
}

interface StepListProps {
  steps: StepListItem[];
  /** Show when each step started and ended, under its name. */
  showTimes?: boolean;
}

/** The steps of a task, backup or restore, in the order the API returns them. */
export function StepList({ steps, showTimes = false }: StepListProps) {
  if (steps.length === 0) return null;
  return (
    <ol
      className="flex flex-col divide-y rounded-md border"
      data-testid="step-list"
    >
      {steps.map((step) => (
        <StepRow key={step.id} step={step} showTimes={showTimes} />
      ))}
    </ol>
  );
}
