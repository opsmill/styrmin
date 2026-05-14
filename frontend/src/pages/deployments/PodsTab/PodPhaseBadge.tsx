import type { PodPhase } from "@/generated/graphql";

/**
 * Pod-phase-specific badge. We can't reuse StatusBadge here because pod phases
 * include SUCCEEDED, which the design specifies as blue — a color the global
 * Badge component does not currently offer. Scope this distinction to pod
 * phases rather than pollute the global badge surface.
 */
interface PodPhaseBadgeProps {
  phase: PodPhase;
}

const phaseClasses: Record<PodPhase, { dot: string; pill: string }> = {
  RUNNING: { dot: "bg-emerald-500", pill: "bg-emerald-50 text-emerald-700" },
  PENDING: { dot: "bg-amber-500", pill: "bg-amber-50 text-amber-800" },
  SUCCEEDED: { dot: "bg-blue-500", pill: "bg-blue-50 text-blue-800" },
  FAILED: { dot: "bg-red-500", pill: "bg-red-50 text-red-800" },
  UNKNOWN: { dot: "bg-zinc-400", pill: "bg-zinc-100 text-zinc-700" },
};

export function PodPhaseBadge({ phase }: PodPhaseBadgeProps) {
  const cls = phaseClasses[phase];
  return (
    <span
      data-pod-phase={phase}
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[11px] font-medium tracking-wide ${cls.pill}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${cls.dot}`} />
      {phase}
    </span>
  );
}
