import { Link, useNavigate } from "@tanstack/react-router";
import { useListDriversQuery } from "@/generated/graphql";
import { PageLayout } from "@/components/PageLayout";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Package, Plus } from "lucide-react";
import { useAutoRefresh } from "@/hooks/useAutoRefresh";
import { AutoRefreshIndicator } from "@/components/AutoRefreshIndicator";

export default function DriverListPage() {
  const navigate = useNavigate();
  const [{ data, fetching, error }, reexecute] = useListDriversQuery();

  const autoRefresh = useAutoRefresh({
    onRefresh: () => reexecute({ requestPolicy: "network-only" }),
  });

  return (
    <PageLayout
      title="Drivers"
      breadcrumbs={[{ label: "Drivers" }]}
      actions={
        <>
          <AutoRefreshIndicator
            enabled={autoRefresh.enabled}
            onToggle={autoRefresh.setEnabled}
            lastRefreshedAt={autoRefresh.lastRefreshedAt}
            onRefreshNow={autoRefresh.refreshNow}
          />
          <Button onClick={() => navigate({ to: "/drivers/add" })}>
            <Plus className="h-4 w-4" />
            Add Driver
          </Button>
        </>
      }
    >
      {fetching && <LoadingState message="Loading drivers..." />}

      {error && (
        <ErrorState
          message={error.message}
          onRetry={() => reexecute({ requestPolicy: "network-only" })}
        />
      )}

      {data && data.applicationDrivers.length === 0 && (
        <EmptyState
          title="No drivers"
          description="No application drivers have been installed yet."
          actionLabel="Add a driver"
          onAction={() => navigate({ to: "/drivers/add" })}
        />
      )}

      {data && data.applicationDrivers.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.applicationDrivers.map((driver) => {
            const latestVersion = driver.versions[0];
            return (
              <Link
                key={driver.id}
                to="/drivers/$driverId"
                params={{ driverId: driver.id }}
              >
                <Card className="hover:border-primary/50 transition-colors cursor-pointer h-full">
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <Package className="h-4 w-4" />
                      {driver.name}
                    </CardTitle>
                    <CardDescription>
                      {driver.versions.length} version
                      {driver.versions.length !== 1 ? "s" : ""}
                    </CardDescription>
                  </CardHeader>
                  <CardContent>
                    {latestVersion && (
                      <div className="flex items-center gap-2">
                        <span className="text-sm text-muted-foreground">
                          Latest: v{latestVersion.version}
                        </span>
                        <Badge variant="secondary">
                          {latestVersion.sourceType}
                        </Badge>
                      </div>
                    )}
                  </CardContent>
                </Card>
              </Link>
            );
          })}
        </div>
      )}
    </PageLayout>
  );
}
