import { useState } from "react";
import { ChevronRight } from "lucide-react";
import type { GetDeploymentPodsQuery } from "@/generated/graphql";
import { classifyStaleness } from "./classifyStaleness";
import { parseContainerState } from "./parseContainerState";
import { KubectlCommands } from "./KubectlCommands";
import { PodPhaseBadge } from "./PodPhaseBadge";

type Pod = GetDeploymentPodsQuery["podStatuses"][number];

// Wire format from the agent reporter — see backend/agent/status/reporter.py
// and ADR-088. snake_case because it is serialized straight from a Python dict
// via the GraphQL JSON scalar; no codegen mapping happens. `kind` is missing
// from entries that an agent older than #574 reported: they are containers.
// A `sidecar` is an init container with `restartPolicy: Always`.
type AgentContainerStatus = {
  name: string;
  kind?: "container" | "init" | "sidecar" | "pod";
  image?: string;
  ready?: boolean;
  state?: string;
  message?: string | null;
  restart_count?: number;
  started_at?: string | null;
};

interface PodRowProps {
  pod: Pod;
  now: Date;
}

export function PodRow({ pod, now }: PodRowProps) {
  const [expanded, setExpanded] = useState(false);
  const staleness = classifyStaleness(pod.lastPolledAt, now);
  const ageSource = pickAgeSource(pod.startedAt, pod.createdOn);

  return (
    <div
      data-testid="pod-row"
      data-pod-name={pod.podName}
      className={expanded ? "bg-muted/30" : undefined}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
        className="flex w-full items-center gap-0 px-5 py-3 text-left hover:bg-muted/20"
      >
        <span className="w-5 shrink-0 text-muted-foreground">
          <ChevronRight
            className={`h-3.5 w-3.5 transition-transform ${expanded ? "rotate-90" : ""}`}
          />
        </span>
        <span className="flex flex-1 min-w-0 items-center gap-2.5">
          <span className="truncate font-mono text-[13px] text-foreground">
            {pod.podName}
          </span>
          {staleness === "stale" && (
            <StaleTag
              label={`stale · polled ${formatAgo(pod.lastPolledAt, now)}`}
            />
          )}
          {staleness === "not_reporting" && (
            <NotReportingTag
              label={
                pod.lastPolledAt
                  ? `agent not reporting · ${formatAgo(pod.lastPolledAt, now)}`
                  : "agent not reporting"
              }
            />
          )}
        </span>
        <span className="w-[110px] shrink-0">
          <PodPhaseBadge phase={pod.phase} />
        </span>
        <span className="w-16 shrink-0 text-right font-mono text-[13px] text-foreground">
          {pod.ready ? "1/1" : "0/1"}
        </span>
        <span className="w-24 shrink-0 pr-4 text-right font-mono text-[13px]">
          <RestartCount count={pod.restartCount} />
        </span>
        <span className="w-[156px] shrink-0 truncate text-[13px] text-muted-foreground">
          {pod.nodeName ?? <em className="not-italic">—</em>}
        </span>
        <span
          className="w-20 shrink-0 text-right text-[13px] text-muted-foreground"
          title={
            ageSource.kind === "createdOn"
              ? "Observed since pod was first reported (started_at unavailable)"
              : undefined
          }
        >
          {ageSource.iso ? formatDuration(ageSource.iso, now) : "—"}
        </span>
      </button>
      {expanded && (
        <ExpandedPanel
          pod={pod}
          now={now}
          ageSource={ageSource}
          staleness={staleness}
        />
      )}
    </div>
  );
}

function ExpandedPanel({
  pod,
  now,
  ageSource,
  staleness,
}: {
  pod: Pod;
  now: Date;
  ageSource: ReturnType<typeof pickAgeSource>;
  staleness: ReturnType<typeof classifyStaleness>;
}) {
  const entries = (pod.containerStatuses ??
    []) as unknown as AgentContainerStatus[];
  const podEntries = entries.filter((entry) => entry.kind === "pod");
  const containers = entries.filter((entry) => entry.kind !== "pod");
  const polledAgo = pod.lastPolledAt
    ? formatAgo(pod.lastPolledAt, now)
    : "never";

  return (
    <div className="flex flex-col gap-4 px-14 pb-5 pt-1">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-muted-foreground">
        <span>
          {ageSource.kind === "createdOn" ? "Observed since " : "Started "}
          <span className="font-medium text-foreground">
            {ageSource.iso ? formatDuration(ageSource.iso, now) : "—"} ago
          </span>
        </span>
        <span className="text-border">·</span>
        <span className="inline-flex items-center gap-1.5">
          <span
            className={`h-1.5 w-1.5 rounded-full ${
              staleness === "fresh"
                ? "bg-emerald-500"
                : staleness === "stale"
                  ? "bg-amber-500"
                  : "bg-red-500"
            }`}
          />
          Polled {polledAgo}
        </span>
      </div>

      {podEntries.map((entry) => (
        <PodConditionNotice key={entry.name} entry={entry} />
      ))}

      <div className="overflow-hidden rounded-lg border border-border bg-background">
        <div className="grid grid-cols-[1fr_220px_64px_120px] items-center gap-3 border-b border-border/60 px-3.5 py-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
          <span>Container</span>
          <span>Image</span>
          <span className="text-right">Restarts</span>
          <span>State</span>
        </div>
        {containers.length === 0 && (
          <div className="px-3.5 py-3 text-[12px] text-muted-foreground">
            No container statuses reported yet.
          </div>
        )}
        {containers.map((c) => {
          const parsed = parseContainerState(c.state);
          return (
            <div
              key={`${c.kind ?? "container"}:${c.name}`}
              data-testid="container-row"
              className="grid grid-cols-[1fr_220px_64px_120px] items-center gap-3 border-b border-border/60 px-3.5 py-2.5 text-[13px] last:border-b-0"
            >
              <span className="flex items-center gap-2 min-w-0">
                <span
                  className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                    c.ready ? "bg-emerald-500" : "bg-zinc-300"
                  }`}
                />
                <span className="truncate font-mono">{c.name}</span>
                {(c.kind === "init" || c.kind === "sidecar") && (
                  <span className="shrink-0 rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                    {c.kind}
                  </span>
                )}
              </span>
              <span className="truncate font-mono text-[12px] text-muted-foreground">
                {c.image ?? "—"}
              </span>
              <span className="text-right font-mono text-muted-foreground">
                {c.restart_count ?? 0}
              </span>
              <span className="text-[12px]">
                <ContainerStateLabel parsed={parsed} />
              </span>
              {c.message && (
                <span
                  data-testid="container-message"
                  className="col-span-4 break-words text-[12px] text-muted-foreground"
                >
                  {c.message}
                </span>
              )}
            </div>
          );
        })}
      </div>

      <KubectlCommands namespace={pod.namespace} podName={pod.podName} />
    </div>
  );
}

// The agent reports a pod that is not scheduled with one `pod` entry: the
// PodScheduled condition, its reason and the scheduler's message.
function PodConditionNotice({ entry }: { entry: AgentContainerStatus }) {
  const { reason } = parseContainerState(entry.state);
  const label = entry.name === "PodScheduled" ? "Not scheduled" : entry.name;
  return (
    <div
      data-testid="pod-condition"
      className="rounded-lg border border-amber-200 bg-amber-50 px-3.5 py-2.5 text-[12px] text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200"
    >
      <span className="font-medium">
        {label}
        {reason ? `: ${reason}` : ""}
      </span>
      {entry.message && <p className="mt-0.5 break-words">{entry.message}</p>}
    </div>
  );
}

function RestartCount({ count }: { count: number }) {
  if (count === 0) {
    return <span className="text-muted-foreground">0</span>;
  }
  if (count >= 5) {
    return (
      <span className="rounded bg-red-50 px-1.5 py-0.5 font-medium text-red-800">
        {count}
      </span>
    );
  }
  return (
    <span className="rounded bg-amber-50 px-1.5 py-0.5 font-medium text-amber-800">
      {count}
    </span>
  );
}

function StaleTag({ label }: { label: string }) {
  return (
    <span
      data-testid="stale-indicator"
      className="inline-flex items-center gap-1.5 rounded bg-amber-50 px-2 py-0.5 text-[11px] font-medium text-amber-800"
    >
      <span className="h-1 w-1 rounded-full bg-amber-500" />
      {label}
    </span>
  );
}

function NotReportingTag({ label }: { label: string }) {
  return (
    <span
      data-testid="not-reporting-indicator"
      className="inline-flex items-center gap-1.5 rounded bg-red-50 px-2 py-0.5 text-[11px] font-medium text-red-800"
    >
      <span className="h-1 w-1 rounded-full bg-red-500" />
      {label}
    </span>
  );
}

function ContainerStateLabel({
  parsed,
}: {
  parsed: ReturnType<typeof parseContainerState>;
}) {
  if (parsed.state === "running") {
    return <span className="text-emerald-700">running</span>;
  }
  if (parsed.state === "waiting") {
    return (
      <span className="text-amber-800">
        waiting{parsed.reason ? `: ${parsed.reason}` : ""}
      </span>
    );
  }
  if (parsed.state === "terminated") {
    return (
      <span className="text-red-800">
        terminated{parsed.reason ? `: ${parsed.reason}` : ""}
      </span>
    );
  }
  return <span className="text-muted-foreground">unknown</span>;
}

function pickAgeSource(
  startedAt: Pod["startedAt"],
  createdOn: Pod["createdOn"],
): { kind: "startedAt" | "createdOn"; iso: string | null } {
  if (typeof startedAt === "string" && startedAt.length > 0) {
    return { kind: "startedAt", iso: startedAt };
  }
  if (typeof createdOn === "string" && createdOn.length > 0) {
    return { kind: "createdOn", iso: createdOn };
  }
  return { kind: "startedAt", iso: null };
}

function formatDuration(iso: string, now: Date): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "—";
  const sec = Math.max(0, Math.floor((now.getTime() - then) / 1_000));
  if (sec < 60) return `${sec}s`;
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min}m`;
  const hr = Math.floor(min / 60);
  const remMin = min - hr * 60;
  if (hr < 24) return remMin > 0 ? `${hr}h ${remMin}m` : `${hr}h`;
  const day = Math.floor(hr / 24);
  return `${day}d`;
}

function formatAgo(iso: string, now: Date): string {
  return `${formatDuration(iso, now)} ago`;
}
