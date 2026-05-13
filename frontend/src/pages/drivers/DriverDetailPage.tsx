import { useState } from "react";
import { useParams, useNavigate } from "@tanstack/react-router";
import { useGetDriverQuery } from "@/generated/graphql";
import { PageLayout } from "@/components/PageLayout";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Plus } from "lucide-react";
import { AutoRefreshIndicator } from "@/components/AutoRefreshIndicator";
import { IfRole } from "@/auth/IfRole";

export default function DriverDetailPage() {
  const { driverId } = useParams({ from: "/drivers/$driverId" });
  const navigate = useNavigate();
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(true);
  const { data, isLoading, error, refetch, dataUpdatedAt } = useGetDriverQuery(
    { applicationDriverId: driverId },
    { refetchInterval: autoRefreshEnabled ? 10_000 : false },
  );

  const driver = data?.applicationDriver;

  if (isLoading) return <LoadingState message="Loading driver..." />;

  if (error) {
    return <ErrorState message={error.message} onRetry={() => refetch()} />;
  }

  if (!driver) {
    return <ErrorState message="Driver not found" />;
  }

  return (
    <PageLayout
      title={driver.name}
      breadcrumbs={[
        { label: "Drivers", href: "/drivers" },
        { label: driver.name },
      ]}
      actions={
        <>
          <AutoRefreshIndicator
            enabled={autoRefreshEnabled}
            onToggle={setAutoRefreshEnabled}
            lastRefreshedAt={dataUpdatedAt ? new Date(dataUpdatedAt) : null}
            onRefreshNow={() => refetch()}
          />
          <IfRole minimum="READ_WRITE">
            <Button onClick={() => navigate({ to: "/drivers/add" })}>
              <Plus className="h-4 w-4" />
              Add Version
            </Button>
          </IfRole>
        </>
      }
    >
      <div
        className="space-y-6"
        data-testid="driver-detail"
        data-driver-id={driver.id}
        data-driver-name={driver.name}
      >
        {driver.versions.map((version) => (
          <Card
            key={version.id}
            data-testid="driver-version-card"
            data-version-id={version.id}
            data-version-label={version.version}
          >
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                v{version.version}
                <Badge variant="secondary">{version.sourceType}</Badge>
              </CardTitle>
              <CardDescription>
                {version.sourceType === "local" ? (
                  <>Path: {version.sourcePath}</>
                ) : (
                  <>
                    {version.sourceRepository}
                    {version.sourceBranch && ` @ ${version.sourceBranch}`}
                  </>
                )}
                {version.supportedVersions && (
                  <span className="ml-2">
                    (supported: {version.supportedVersions})
                  </span>
                )}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Parameters */}
              {version.parameters.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium mb-2">Parameters</h3>
                  <div className="rounded-md border">
                    <table className="w-full">
                      <thead>
                        <tr className="border-b bg-muted/50">
                          <th className="px-4 py-2 text-left text-sm font-medium">
                            Name
                          </th>
                          <th className="px-4 py-2 text-left text-sm font-medium">
                            Label
                          </th>
                          <th className="px-4 py-2 text-left text-sm font-medium">
                            Kind
                          </th>
                          <th className="px-4 py-2 text-left text-sm font-medium">
                            Default
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {version.parameters.map((param) => (
                          <tr
                            key={param.name}
                            className="border-b last:border-0"
                          >
                            <td className="px-4 py-2 text-sm font-mono">
                              {param.name}
                            </td>
                            <td className="px-4 py-2 text-sm">{param.label}</td>
                            <td className="px-4 py-2 text-sm">{param.kind}</td>
                            <td className="px-4 py-2 text-sm font-mono">
                              {param.default !== null &&
                              param.default !== undefined
                                ? String(param.default)
                                : "-"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Helm Chart */}
              <div>
                <h3 className="text-sm font-medium mb-2">Helm Chart</h3>
                <div className="text-sm space-y-1">
                  <p>
                    <span className="text-muted-foreground">Name:</span>{" "}
                    {version.helmChart.name}
                  </p>
                  <p>
                    <span className="text-muted-foreground">Version:</span>{" "}
                    {version.helmChart.version}
                  </p>
                  <p>
                    <span className="text-muted-foreground">Repository:</span>{" "}
                    {version.helmChart.repository}
                  </p>
                </div>
              </div>

              {/* Actions */}
              {version.actions.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium mb-2">Actions</h3>
                  <div className="space-y-2">
                    {version.actions.map((action) => (
                      <div key={action.id} className="text-sm">
                        <span className="font-medium">{action.name}</span>
                        <span className="text-muted-foreground">
                          {" "}
                          - {action.description}
                        </span>
                        <span className="text-muted-foreground text-xs ml-2">
                          ({action.location})
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Component Configs */}
              {version.componentConfigs.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium mb-2">
                    Component Configs
                  </h3>
                  <div className="space-y-2">
                    {version.componentConfigs.map((cc) => (
                      <div key={cc.id}>
                        <p className="text-sm font-medium">{cc.name}</p>
                        {cc.config && (
                          <pre className="text-xs bg-muted p-2 rounded-md overflow-auto mt-1">
                            {JSON.stringify(cc.config, null, 2)}
                          </pre>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Components */}
              {version.components && (
                <div>
                  <h3 className="text-sm font-medium mb-2">Components</h3>
                  <pre className="text-xs bg-muted p-2 rounded-md overflow-auto">
                    {JSON.stringify(version.components, null, 2)}
                  </pre>
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </PageLayout>
  );
}
