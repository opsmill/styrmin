import { Link } from "react-router";
import { useListEnvironmentsQuery } from "@/generated/graphql";
import { PageLayout } from "@/components/PageLayout";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { StatusBadge } from "@/components/StatusBadge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Server } from "lucide-react";
import { useAutoRefresh } from "@/hooks/useAutoRefresh";
import { AutoRefreshIndicator } from "@/components/AutoRefreshIndicator";
import { CreateEnvironmentDialog } from "./CreateEnvironmentDialog";

export default function EnvironmentListPage() {
  const [{ data, fetching, error }, reexecute] = useListEnvironmentsQuery();

  const autoRefresh = useAutoRefresh({
    onRefresh: () => reexecute({ requestPolicy: "network-only" }),
  });

  return (
    <PageLayout
      title="Environments"
      actions={
        <div className="flex items-center gap-2">
          <AutoRefreshIndicator
            enabled={autoRefresh.enabled}
            onToggle={autoRefresh.setEnabled}
            lastRefreshedAt={autoRefresh.lastRefreshedAt}
            onRefreshNow={autoRefresh.refreshNow}
          />
          <CreateEnvironmentDialog
            onCreated={() => reexecute({ requestPolicy: "network-only" })}
          />
        </div>
      }
    >
      {fetching && <LoadingState message="Loading environments..." />}

      {error && (
        <ErrorState
          message={error.message}
          onRetry={() => reexecute({ requestPolicy: "network-only" })}
        />
      )}

      {data && data.environments.length === 0 && (
        <EmptyState
          title="No environments"
          description="No environments have been configured yet."
        />
      )}

      {data && data.environments.length > 0 && (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {data.environments.map((env) => (
            <Link key={env.id} to={`/environments/${env.id}`}>
              <Card className="hover:border-primary/50 transition-colors cursor-pointer h-full">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Server className="h-4 w-4" />
                    {env.name}
                  </CardTitle>
                  <CardDescription>Cluster: {env.cluster.name}</CardDescription>
                </CardHeader>
                <CardContent>
                  {env.deployments.length === 0 ? (
                    <p className="text-sm text-muted-foreground">
                      No deployments
                    </p>
                  ) : (
                    <div className="space-y-1">
                      <p className="text-sm font-medium">
                        {env.deployments.length} deployment
                        {env.deployments.length !== 1 ? "s" : ""}
                      </p>
                      <div className="flex flex-wrap gap-1">
                        {env.deployments.map((d) => (
                          <StatusBadge key={d.id} status={d.status} />
                        ))}
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </PageLayout>
  );
}
