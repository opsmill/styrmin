import { useParams, Link, useNavigate } from "react-router";
import {
  useGetEnvironmentQuery,
  useListBackupStorageLocationsQuery,
  useAssignBackupStorageLocationMutation,
  useUnassignBackupStorageLocationMutation,
} from "@/generated/graphql";
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
import { useAutoRefresh } from "@/hooks/useAutoRefresh";
import { AutoRefreshIndicator } from "@/components/AutoRefreshIndicator";

export default function EnvironmentDetailPage() {
  const { environmentId } = useParams();
  const navigate = useNavigate();
  const [{ data, fetching, error }, reexecute] = useGetEnvironmentQuery({
    variables: { environmentId: environmentId! },
    pause: !environmentId,
  });

  const [{ data: bslData }] = useListBackupStorageLocationsQuery();
  const [, executeAssign] = useAssignBackupStorageLocationMutation();
  const [, executeUnassign] = useUnassignBackupStorageLocationMutation();

  const environment = data?.environment;

  const handleBslChange = async (value: string) => {
    if (!environmentId) return;
    if (value === "__none__") {
      await executeUnassign({ environmentId });
    } else {
      await executeAssign({
        environmentId,
        backupStorageLocationId: value,
      });
    }
    reexecute({ requestPolicy: "network-only" });
  };

  const autoRefresh = useAutoRefresh({
    onRefresh: () => reexecute({ requestPolicy: "network-only" }),
  });

  if (fetching) return <LoadingState message="Loading environment..." />;

  if (error) {
    return (
      <ErrorState
        message={error.message}
        onRetry={() => reexecute({ requestPolicy: "network-only" })}
      />
    );
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
            enabled={autoRefresh.enabled}
            onToggle={autoRefresh.setEnabled}
            lastRefreshedAt={autoRefresh.lastRefreshedAt}
            onRefreshNow={autoRefresh.refreshNow}
          />
          <Button
            onClick={() => navigate(`/environments/${environmentId}/deploy`)}
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
          onAction={() => navigate(`/environments/${environmentId}/deploy`)}
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
                      to={`/environments/${environmentId}/deployments/${deployment.id}`}
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
