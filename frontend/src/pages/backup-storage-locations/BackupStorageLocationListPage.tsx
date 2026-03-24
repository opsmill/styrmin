import { Link } from "react-router";
import { useListBackupStorageLocationsQuery } from "@/generated/graphql";
import { PageLayout } from "@/components/PageLayout";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { HardDrive } from "lucide-react";
import { useAutoRefresh } from "@/hooks/useAutoRefresh";
import { AutoRefreshIndicator } from "@/components/AutoRefreshIndicator";
import { CreateBackupStorageLocationDialog } from "./CreateBackupStorageLocationDialog";

export default function BackupStorageLocationListPage() {
  const [{ data, fetching, error }, reexecute] =
    useListBackupStorageLocationsQuery();

  const autoRefresh = useAutoRefresh({
    onRefresh: () => reexecute({ requestPolicy: "network-only" }),
  });

  return (
    <PageLayout
      title="Backup Storage Locations"
      actions={
        <div className="flex items-center gap-2">
          <AutoRefreshIndicator
            enabled={autoRefresh.enabled}
            onToggle={autoRefresh.setEnabled}
            lastRefreshedAt={autoRefresh.lastRefreshedAt}
            onRefreshNow={autoRefresh.refreshNow}
          />
          <CreateBackupStorageLocationDialog
            onCreated={() => reexecute({ requestPolicy: "network-only" })}
          />
        </div>
      }
    >
      {fetching && (
        <LoadingState message="Loading backup storage locations..." />
      )}

      {error && (
        <ErrorState
          message={error.message}
          onRetry={() => reexecute({ requestPolicy: "network-only" })}
        />
      )}

      {data && data.backupStorageLocations.length === 0 && (
        <EmptyState
          title="No backup storage locations"
          description="No backup storage locations have been configured yet."
        />
      )}

      {data && data.backupStorageLocations.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.backupStorageLocations.map((bsl) => (
            <Link key={bsl.id} to={`/backup-storage-locations/${bsl.id}`}>
              <Card className="hover:border-primary/50 transition-colors cursor-pointer h-full">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <HardDrive className="h-4 w-4" />
                    {bsl.name}
                  </CardTitle>
                  <CardDescription>
                    {bsl.endpoint} / {bsl.bucket}
                  </CardDescription>
                </CardHeader>
                <CardContent>
                  <p className="text-sm text-muted-foreground">
                    {bsl.environmentCount} environment
                    {bsl.environmentCount !== 1 ? "s" : ""}
                  </p>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </PageLayout>
  );
}
