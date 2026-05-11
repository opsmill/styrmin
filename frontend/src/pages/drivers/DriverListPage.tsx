import { useState } from "react";
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
import { AutoRefreshIndicator } from "@/components/AutoRefreshIndicator";
import { IfRole } from "@/auth/IfRole";
import { useEffectiveRole } from "@/auth/useEffectiveRole";

export default function DriverListPage() {
  const navigate = useNavigate();
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(true);
  const effectiveRole = useEffectiveRole();
  const canWrite =
    effectiveRole === "READ_WRITE" || effectiveRole === "ADMIN";
  const { data, isLoading, error, refetch, dataUpdatedAt } =
    useListDriversQuery(undefined, {
      refetchInterval: autoRefreshEnabled ? 10_000 : false,
    });

  return (
    <PageLayout
      title="Drivers"
      breadcrumbs={[{ label: "Drivers" }]}
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
              Add Driver
            </Button>
          </IfRole>
        </>
      }
    >
      {isLoading && <LoadingState message="Loading drivers..." />}

      {error && (
        <ErrorState message={error.message} onRetry={() => refetch()} />
      )}

      {data && data.applicationDrivers.length === 0 && (
        <EmptyState
          title="No drivers"
          description="No application drivers have been installed yet."
          actionLabel={canWrite ? "Add a driver" : undefined}
          onAction={canWrite ? () => navigate({ to: "/drivers/add" }) : undefined}
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
