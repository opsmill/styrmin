import { useMemo, useState } from "react";
import { useGetDeploymentPodsQuery } from "@/generated/graphql";
import { AutoRefreshIndicator } from "@/components/AutoRefreshIndicator";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { groupPodsByComponent } from "./groupPodsByComponent";
import { PodSection } from "./PodSection";

interface PodsTabProps {
  deploymentId: string;
  /** Whether the Pods tab is the currently-active tab on the deployment page. */
  isActive: boolean;
  /** Declared components from the deployment spec — drives the "declared" buckets. */
  declaredComponents: ReadonlyArray<{ name: string }>;
  /**
   * Phase of the parent deployment (e.g. "running", "creating"). Used to tailor
   * the empty state so a stuck agent on a RUNNING deployment is distinguishable
   * from a not-yet-converged deployment.
   */
  deploymentStatus: string;
  /** Switch to the Timeline tab (used by the RUNNING empty state). */
  onOpenTimeline: () => void;
}

export function PodsTab({
  deploymentId,
  isActive,
  declaredComponents,
  deploymentStatus,
  onOpenTimeline,
}: PodsTabProps) {
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(true);

  const query = useGetDeploymentPodsQuery(
    { deploymentId },
    {
      enabled: isActive,
      refetchInterval: isActive && autoRefreshEnabled ? 10_000 : false,
    },
  );

  const now = useMemo(() => new Date(), [query.dataUpdatedAt]);

  const groups = useMemo(() => {
    return groupPodsByComponent(
      query.data?.podStatuses ?? [],
      declaredComponents,
    );
  }, [query.data?.podStatuses, declaredComponents]);

  const podCount = query.data?.podStatuses.length ?? 0;

  return (
    <div className="flex flex-col gap-6 pt-2">
      <div className="flex items-end justify-between gap-6">
        <div className="flex flex-col gap-1">
          <h2 className="text-[18px] font-semibold tracking-tight text-foreground">
            Pods
          </h2>
          <p className="text-[13px] text-muted-foreground">
            Observed pod state reported by the Styrmin agent. Grouped by
            component.
          </p>
        </div>
        <AutoRefreshIndicator
          enabled={autoRefreshEnabled && isActive}
          onToggle={setAutoRefreshEnabled}
          lastRefreshedAt={
            query.dataUpdatedAt ? new Date(query.dataUpdatedAt) : null
          }
          onRefreshNow={() => {
            void query.refetch();
          }}
        />
      </div>

      {query.isLoading && podCount === 0 ? (
        <LoadingState />
      ) : query.isError ? (
        <ErrorState
          title="Couldn't load pod statuses"
          message={(query.error as Error).message}
          onRetry={() => {
            void query.refetch();
          }}
        />
      ) : podCount === 0 ? (
        <EmptyState
          deploymentStatus={deploymentStatus}
          onOpenTimeline={onOpenTimeline}
        />
      ) : (
        <div className="flex flex-col gap-6">
          {groups.declared.map(({ componentName, pods }) => (
            <PodSection
              key={`declared:${componentName}`}
              variant="declared"
              componentName={componentName}
              pods={pods}
              now={now}
            />
          ))}
          {groups.drifting.map(({ componentName, pods }) => (
            <PodSection
              key={`drift:${componentName}`}
              variant="drifting"
              componentName={componentName}
              pods={pods}
              now={now}
            />
          ))}
          {groups.unlabeled.length > 0 && (
            <PodSection
              variant="unlabeled"
              componentName="Unlabeled"
              pods={groups.unlabeled}
              now={now}
            />
          )}
        </div>
      )}
    </div>
  );
}

function EmptyState({
  deploymentStatus,
  onOpenTimeline,
}: {
  deploymentStatus: string;
  onOpenTimeline: () => void;
}) {
  const isRunning = deploymentStatus.toLowerCase() === "running";
  return (
    <div
      data-testid="pods-empty-state"
      data-deployment-status={deploymentStatus}
      className="flex flex-col items-start gap-3 rounded-xl border border-dashed border-border bg-background px-6 py-8 text-[13px]"
    >
      {isRunning ? (
        <>
          <p className="text-foreground">
            This deployment is <span className="font-medium">running</span>, but
            no pods have been reported.
          </p>
          <p className="text-muted-foreground">
            The Styrmin agent may not be reaching the cluster. Check the
            Timeline tab for agent reachability errors.
          </p>
          <button
            type="button"
            onClick={onOpenTimeline}
            className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-[12px] font-medium text-foreground hover:bg-muted"
          >
            Open Timeline
          </button>
        </>
      ) : (
        <>
          <p className="text-foreground">No pods have been reported yet.</p>
          <p className="text-muted-foreground">
            Current deployment phase:{" "}
            <span className="font-medium">{deploymentStatus}</span>. Pods will
            appear here as the Styrmin agent reports them.
          </p>
        </>
      )}
    </div>
  );
}
