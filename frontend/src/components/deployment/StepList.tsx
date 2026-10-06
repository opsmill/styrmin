import { useEffect, useState } from "react";
import {
  Circle,
  CircleCheck,
  CircleSlash,
  CircleX,
  LoaderCircle,
  type LucideIcon,
} from "lucide-react";
import type { StepKind, StepStatus } from "@/generated/graphql";
import { cn } from "@/lib/utils";

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
  hasOutput?: boolean;
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

function StepRow({ step }: { step: StepListItem }) {
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
      className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm"
      data-testid="step-row"
      data-step-id={step.id}
      data-step-key={step.key}
      data-step-kind={step.kind}
      data-step-status={step.status}
      data-step-started-at={step.startedAt ?? ""}
      data-step-ended-at={step.endedAt ?? ""}
      data-step-attempts={step.attemptCount}
      data-step-has-output={step.hasOutput ? "true" : "false"}
    >
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
    </li>
  );
}

interface StepListProps {
  steps: StepListItem[];
}

/** The steps of a task, backup or restore, in the order the API returns them. */
export function StepList({ steps }: StepListProps) {
  if (steps.length === 0) return null;
  return (
    <ol
      className="flex flex-col divide-y rounded-md border"
      data-testid="step-list"
    >
      {steps.map((step) => (
        <StepRow key={step.id} step={step} />
      ))}
    </ol>
  );
}
