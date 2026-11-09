import type { PodPhase } from "@/generated/graphql";
import { classifyStaleness } from "./classifyStaleness";

type PodLike = {
  phase: PodPhase;
  ready: boolean;
  lastPolledAt?: string | null;
};

// A pod in phase RUNNING whose containers are not all ready, for example one
// in CrashLoopBackOff, counts apart from the ready ones so it never shows green.
type ChipKind = PodPhase | "NOT_READY";

interface PhaseChipsProps {
  pods: readonly PodLike[];
  now: Date;
}

const phaseStyles: Record<
  ChipKind,
  { pill: string; dot: string; label: string }
> = {
  RUNNING: {
    pill: "bg-emerald-50 text-emerald-700",
    dot: "bg-emerald-500",
    label: "running",
  },
  NOT_READY: {
    pill: "bg-amber-50 text-amber-800",
    dot: "bg-amber-500",
    label: "not ready",
  },
  PENDING: {
    pill: "bg-amber-50 text-amber-800",
    dot: "bg-amber-500",
    label: "pending",
  },
  SUCCEEDED: {
    pill: "bg-blue-50 text-blue-800",
    dot: "bg-blue-500",
    label: "succeeded",
  },
  FAILED: {
    pill: "bg-red-50 text-red-800",
    dot: "bg-red-500",
    label: "failed",
  },
  UNKNOWN: {
    pill: "bg-zinc-100 text-zinc-700",
    dot: "bg-zinc-400",
    label: "unknown",
  },
};

// Stable display order so chip positions don't shuffle between renders.
const PHASE_ORDER: ChipKind[] = [
  "RUNNING",
  "NOT_READY",
  "PENDING",
  "SUCCEEDED",
  "FAILED",
  "UNKNOWN",
];

export function PhaseChips({ pods, now }: PhaseChipsProps) {
  if (pods.length === 0) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-dashed border-border bg-muted/30 px-2.5 py-0.5 text-[11px] font-medium tracking-wide text-muted-foreground">
        <span className="h-1.5 w-1.5 rounded-full border border-dashed border-muted-foreground/60" />
        no pods
      </span>
    );
  }

  const counts = new Map<ChipKind, number>();
  let staleCount = 0;
  for (const pod of pods) {
    const kind: ChipKind =
      pod.phase === "RUNNING" && !pod.ready ? "NOT_READY" : pod.phase;
    counts.set(kind, (counts.get(kind) ?? 0) + 1);
    if (classifyStaleness(pod.lastPolledAt, now) !== "fresh") staleCount += 1;
  }

  return (
    <span className="inline-flex items-center gap-1.5">
      {PHASE_ORDER.map((phase) => {
        const count = counts.get(phase) ?? 0;
        if (count === 0) return null;
        const s = phaseStyles[phase];
        return (
          <span
            key={phase}
            data-testid={`phase-chip-${phase.toLowerCase().replace("_", "-")}`}
            className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-medium tracking-wide ${s.pill}`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} />
            {count} {s.label}
          </span>
        );
      })}
      {staleCount > 0 && (
        <span
          data-testid="phase-chip-stale"
          className="inline-flex items-center gap-1.5 rounded-md bg-amber-50 px-2 py-0.5 text-[11px] font-medium tracking-wide text-amber-800"
        >
          <span className="h-1.5 w-1.5 rounded-full bg-amber-500" />
          {staleCount === 1 ? "stale" : `${staleCount} stale`}
        </span>
      )}
    </span>
  );
}
