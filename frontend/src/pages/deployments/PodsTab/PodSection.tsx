import type { ReactNode } from "react";
import type { GetDeploymentPodsQuery } from "@/generated/graphql";
import { PodRow } from "./PodRow";

type Pod = GetDeploymentPodsQuery["podStatuses"][number];

type SectionVariant = "declared" | "drifting" | "unlabeled";

interface PodSectionProps {
  variant: SectionVariant;
  /** Component label; for variant="unlabeled" this is shown as a literal "Unlabeled" header. */
  componentName: string;
  pods: Pod[];
  now: Date;
}

export function PodSection({
  variant,
  componentName,
  pods,
  now,
}: PodSectionProps) {
  const isDrift = variant === "drifting";
  return (
    <div
      data-testid="pod-section"
      data-variant={variant}
      data-component={componentName}
      className={
        isDrift
          ? "overflow-hidden rounded-xl border border-amber-300 bg-background"
          : "overflow-hidden rounded-xl border border-border bg-background"
      }
    >
      <Header
        variant={variant}
        componentName={componentName}
        pods={pods}
        isDrift={isDrift}
      />
      {pods.length === 0 ? (
        <EmptyDeclaredPlaceholder />
      ) : (
        <>
          <ColumnHeaders />
          {pods.map((pod) => (
            <div
              key={pod.id}
              className="border-b border-border/60 last:border-b-0"
            >
              <PodRow pod={pod} now={now} />
            </div>
          ))}
        </>
      )}
    </div>
  );
}

function Header({
  variant,
  componentName,
  pods,
  isDrift,
}: {
  variant: SectionVariant;
  componentName: string;
  pods: Pod[];
  isDrift: boolean;
}) {
  const readyCount = pods.filter((p) => p.ready).length;
  const totalCount = pods.length;
  return (
    <div
      className={
        isDrift
          ? "flex items-center gap-3 border-b border-amber-200 bg-amber-50 px-5 py-3.5"
          : "flex items-center gap-3 border-b border-border bg-muted/40 px-5 py-3.5"
      }
    >
      {variant === "unlabeled" ? (
        <span className="text-[13px] font-semibold text-foreground">
          Unlabeled
        </span>
      ) : (
        <span className="font-mono text-[13px] font-semibold text-foreground">
          {componentName}
        </span>
      )}
      <VariantTag variant={variant} />
      <span className="flex-1" />
      <PodCountSummary
        pods={pods}
        readyCount={readyCount}
        totalCount={totalCount}
        isDrift={isDrift}
      />
    </div>
  );
}

function VariantTag({ variant }: { variant: SectionVariant }) {
  if (variant === "declared") {
    return <Tag tone="blue">declared</Tag>;
  }
  if (variant === "drifting") {
    return <Tag tone="amber">unknown component</Tag>;
  }
  return <Tag tone="zinc">no styrmin/component label</Tag>;
}

function Tag({
  tone,
  children,
}: {
  tone: "blue" | "amber" | "zinc";
  children: ReactNode;
}) {
  const cls: Record<typeof tone, string> = {
    blue: "bg-blue-50 text-blue-700",
    amber: "bg-amber-100 text-amber-800",
    zinc: "bg-zinc-100 text-zinc-700",
  };
  return (
    <span
      className={`rounded px-2 py-0.5 text-[11px] font-medium tracking-wide ${cls[tone]}`}
    >
      {children}
    </span>
  );
}

function PodCountSummary({
  pods,
  readyCount,
  totalCount,
  isDrift,
}: {
  pods: Pod[];
  readyCount: number;
  totalCount: number;
  isDrift: boolean;
}) {
  if (totalCount === 0) {
    return <span className="text-[12px] text-muted-foreground">0 pods</span>;
  }
  if (isDrift) {
    return (
      <span className="text-[12px] text-amber-800">
        Observed label · not in driver spec
      </span>
    );
  }
  return (
    <span className="text-[12px] text-muted-foreground">
      {totalCount} {totalCount === 1 ? "pod" : "pods"}
      {readyCount > 0 && (
        <>
          {" · "}
          <span className="font-medium text-emerald-700">
            {readyCount} ready
          </span>
        </>
      )}
      {(() => {
        // Reserved for future readyCount === 0 styling; pods param keeps
        // the closure honest about the dataset shape.
        void pods;
        return null;
      })()}
    </span>
  );
}

function ColumnHeaders() {
  return (
    <div className="flex items-center px-5 py-2.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground border-b border-border/60">
      <span className="w-5 shrink-0" />
      <span className="flex-1 min-w-0">Pod</span>
      <span className="w-[110px] shrink-0">Phase</span>
      <span className="w-16 shrink-0 text-right">Ready</span>
      <span className="w-24 shrink-0 pr-4 text-right">Restarts</span>
      <span className="w-[156px] shrink-0">Node</span>
      <span className="w-20 shrink-0 text-right">Age</span>
    </div>
  );
}

function EmptyDeclaredPlaceholder() {
  return (
    <div className="flex items-center gap-2.5 px-5 py-5 text-[13px] text-muted-foreground">
      <span className="h-4 w-4 shrink-0 rounded-full border border-dashed border-border" />
      No pods reported for this component.
    </div>
  );
}
