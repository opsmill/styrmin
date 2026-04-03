import { useState } from "react";
import { useParams, Link, useNavigate } from "@tanstack/react-router";
import {
  useGetEnvironmentQuery,
  useListBackupStorageLocationsQuery,
  useAssignBackupStorageLocationMutation,
  useUnassignBackupStorageLocationMutation,
} from "@/generated/graphql";
import { useQueryClient } from "@tanstack/react-query";
import { PageLayout } from "@/components/PageLayout";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { StatusBadge } from "@/components/StatusBadge";
import { ConfigSection } from "@/components/ConfigSection";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Plus } from "lucide-react";
import { AutoRefreshIndicator } from "@/components/AutoRefreshIndicator";

export default function EnvironmentDetailPage() {
  const { environmentId } = useParams({
    from: "/environments/$environmentId",
  });
  const navigate = useNavigate();
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(true);
  const { data, isLoading, error, refetch, dataUpdatedAt } =
    useGetEnvironmentQuery(
      { environmentId },
      { refetchInterval: autoRefreshEnabled ? 10_000 : false },
    );

  const { data: bslData } = useListBackupStorageLocationsQuery();
  const assignBslMutation = useAssignBackupStorageLocationMutation();
  const unassignBslMutation = useUnassignBackupStorageLocationMutation();
  const queryClient = useQueryClient();

  const environment = data?.environment;

  const handleBslChange = async (value: string) => {
    try {
      if (value === "__none__") {
        await unassignBslMutation.mutateAsync({ environmentId });
      } else {
        await assignBslMutation.mutateAsync({
          environmentId,
          backupStorageLocationId: value,
        });
      }
      queryClient.invalidateQueries({ queryKey: ["GetEnvironment"] });
    } catch {
      // Error handling can be added if needed
    }
  };

  if (isLoading) return <LoadingState message="Loading environment..." />;

  if (error) {
    return <ErrorState message={error.message} onRetry={() => refetch()} />;
  }

  if (!environment) {
    return <ErrorState message="Environment not found" />;
  }

  return (
    <PageLayout
      title={environment.name}
      breadcrumbs={[{ label: environment.name }]}
      actions={
        <>
          <AutoRefreshIndicator
            enabled={autoRefreshEnabled}
            onToggle={setAutoRefreshEnabled}
            lastRefreshedAt={dataUpdatedAt ? new Date(dataUpdatedAt) : null}
            onRefreshNow={() => refetch()}
          />
          <Button
            onClick={() =>
              navigate({
                to: "/environments/$environmentId/deploy",
                params: { environmentId },
              })
            }
          >
            <Plus className="h-4 w-4" />
            Deploy
          </Button>
        </>
      }
    >
      <div className="mb-6 space-y-3">
        <p className="text-sm text-muted-foreground">
          Cluster:{" "}
          <span className="font-medium text-foreground">
            {environment.cluster.name}
          </span>
        </p>
        <div className="flex items-center gap-3">
          <Label className="text-sm text-muted-foreground whitespace-nowrap">
            Backup Storage:
          </Label>
          <Select
            value={environment.backupStorageLocation?.id ?? "__none__"}
            onValueChange={handleBslChange}
          >
            <SelectTrigger className="w-64">
              <SelectValue placeholder="Cluster default" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="__none__">Cluster default</SelectItem>
              {bslData?.backupStorageLocations.map((bsl) => (
                <SelectItem key={bsl.id} value={bsl.id}>
                  {bsl.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      {environment.config &&
        Object.values(environment.config).some((v) => v != null) && (
          <Card className="mb-6">
            <CardHeader>
              <CardTitle className="text-base">Configuration</CardTitle>
            </CardHeader>
            <CardContent>
              <ConfigSection config={environment.config} />
            </CardContent>
          </Card>
        )}

      {environment.deployments.length === 0 ? (
        <EmptyState
          title="No deployments"
          description="No applications have been deployed to this environment yet."
          actionLabel="Deploy an application"
          onAction={() =>
            navigate({
              to: "/environments/$environmentId/deploy",
              params: { environmentId },
            })
          }
        />
      ) : (
        <div className="rounded-md border">
          <table className="w-full">
            <thead>
              <tr className="border-b bg-muted/50">
                <th className="px-4 py-3 text-left text-sm font-medium">
                  Name
                </th>
                <th className="px-4 py-3 text-left text-sm font-medium">
                  Status
                </th>
                <th className="px-4 py-3 text-left text-sm font-medium">
                  Version
                </th>
                <th className="px-4 py-3 text-left text-sm font-medium">
                  Components
                </th>
              </tr>
            </thead>
            <tbody>
              {environment.deployments.map((deployment) => (
                <tr
                  key={deployment.id}
                  className="border-b last:border-0 hover:bg-muted/30 transition-colors"
                >
                  <td className="px-4 py-3 text-sm">
                    <Link
                      to="/environments/$environmentId/deployments/$deploymentId"
                      params={{
                        environmentId,
                        deploymentId: deployment.id,
                      }}
                      className="font-medium hover:underline"
                    >
                      {deployment.name}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-sm">
                    <StatusBadge status={deployment.status} />
                  </td>
                  <td className="px-4 py-3 text-sm font-mono">
                    {deployment.applicationVersion}
                  </td>
                  <td className="px-4 py-3 text-sm">
                    {deployment.components.length}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </PageLayout>
  );
}
