import { useMemo, useState } from "react";
import { useNavigate, useParams } from "@tanstack/react-router";
import { Plus } from "lucide-react";
import { useGetDriverQuery } from "@/generated/graphql";
import { PageLayout } from "@/components/PageLayout";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { Button } from "@/components/ui/button";
import { IfRole } from "@/auth/IfRole";
import { DriverHeader } from "./DriverHeader";
import { VersionList } from "./driver-detail/VersionList";
import { VersionDetail } from "./driver-detail/VersionDetail";
import type { DriverVersionDetail, TabId } from "./driver-detail/types";

/**
 * Driver detail page — left-rail version list + right-pane tabbed view.
 *
 * Owns:
 *   - the typed `useGetDriverQuery` poll (10s auto-refresh, toggleable),
 *   - the `selectedVersionId` cursor (initialised after first successful
 *     load to the newest-by-`createdOn` version),
 *   - the `activeTab` cursor (defaults to "overview"; preserved across
 *     version switches per FR-007),
 *   - the EC-002 silent fallback: when the previously-selected version
 *     disappears between refreshes, we drop the cursor and let the
 *     selection effect re-pick the new newest.
 */
export default function DriverDetailPage() {
  const { driverId } = useParams({ from: "/drivers/$driverId" });
  const navigate = useNavigate();
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(true);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(
    null,
  );
  const [activeTab, setActiveTab] = useState<TabId>("overview");

  const { data, isLoading, error, refetch, dataUpdatedAt } = useGetDriverQuery(
    { applicationDriverId: driverId },
    { refetchInterval: autoRefreshEnabled ? 10_000 : false },
  );

  const driver = data?.applicationDriver;
  const versions = useMemo(() => driver?.versions ?? [], [driver?.versions]);

  // EC-002 silent fallback + initial selection. Computed during render
  // (not in an effect) so the right pane never flickers through a
  // "no selection" frame when the cursor needs reconciling.
  //
  // The setState-during-render is guarded by an equality check on a
  // prior-value cursor (`reconciledVersionId`) — the officially
  // recommended pattern to avoid the cascading-renders warning under
  // the React Compiler (`react-hooks/set-state-in-effect`).
  const reconciledVersionId = reconcileSelectedVersion(
    versions,
    selectedVersionId,
  );
  if (reconciledVersionId !== selectedVersionId) {
    setSelectedVersionId(reconciledVersionId);
  }

  if (isLoading && !data) return <LoadingState message="Loading driver..." />;

  if (error) {
    return <ErrorState message={error.message} onRetry={() => refetch()} />;
  }

  if (!driver) {
    return <ErrorState message="Driver not found" />;
  }

  const selectedVersion: DriverVersionDetail | null =
    versions.find((v) => v.id === reconciledVersionId) ?? null;

  return (
    <PageLayout
      title={driver.name}
      breadcrumbs={[
        { label: "Drivers", href: "/drivers" },
        { label: driver.name },
      ]}
      actions={
        <DriverHeader
          driver={driver}
          autoRefreshEnabled={autoRefreshEnabled}
          onToggleAutoRefresh={setAutoRefreshEnabled}
          lastRefreshedAt={dataUpdatedAt ? new Date(dataUpdatedAt) : null}
          onRefreshNow={() => refetch()}
          onAddVersion={() => navigate({ to: "/drivers/add" })}
        />
      }
    >
      <div
        data-testid="driver-detail"
        data-driver-id={driver.id}
        data-driver-name={driver.name}
      >
        {versions.length === 0 ? (
          <EmptyVersionsState
            onAddVersion={() => navigate({ to: "/drivers/add" })}
          />
        ) : (
          <div className="flex gap-6">
            <VersionList
              versions={versions}
              selectedVersionId={reconciledVersionId}
              onSelect={setSelectedVersionId}
            />
            {selectedVersion && (
              <VersionDetail
                version={selectedVersion}
                activeTab={activeTab}
                onTabChange={setActiveTab}
              />
            )}
          </div>
        )}
      </div>
    </PageLayout>
  );
}

function pickNewestVersionId(versions: readonly DriverVersionDetail[]): string {
  return [...versions].sort(
    (a, b) => Date.parse(b.createdOn) - Date.parse(a.createdOn),
  )[0].id;
}

/**
 * Reconcile the persisted cursor against the freshest versions list.
 *
 * Returns:
 *   - `null` when the list is empty,
 *   - the existing `current` when it still points at a present row,
 *   - the newest-by-`createdOn` id otherwise (initial selection + the
 *     EC-002 silent fallback).
 */
function reconcileSelectedVersion(
  versions: readonly DriverVersionDetail[],
  current: string | null,
): string | null {
  if (versions.length === 0) {
    return null;
  }
  if (current !== null && versions.some((v) => v.id === current)) {
    return current;
  }
  return pickNewestVersionId(versions);
}

function EmptyVersionsState({ onAddVersion }: { onAddVersion: () => void }) {
  return (
    <div
      className="flex flex-col items-center justify-center gap-3 rounded-md border border-dashed border-border py-12"
      data-testid="driver-empty-versions"
    >
      <p className="text-sm text-muted-foreground">No versions yet</p>
      <IfRole minimum="READ_WRITE">
        <Button onClick={onAddVersion} data-testid="driver-empty-add-version">
          <Plus className="h-4 w-4" />
          Add Version
        </Button>
      </IfRole>
    </div>
  );
}
