import { useParams, Link } from "react-router";
import { useGetClusterQuery } from "@/generated/graphql";
import { PageLayout } from "@/components/PageLayout";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { ConfigSection } from "@/components/ConfigSection";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useAutoRefresh } from "@/hooks/useAutoRefresh";
import { AutoRefreshIndicator } from "@/components/AutoRefreshIndicator";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString();
}

export default function ClusterDetailPage() {
  const { clusterId } = useParams();
  const [{ data, fetching, error }, reexecute] = useGetClusterQuery({
    variables: { clusterId: clusterId! },
    pause: !clusterId,
  });

  const cluster = data?.cluster;

  const autoRefresh = useAutoRefresh({
    onRefresh: () => reexecute({ requestPolicy: "network-only" }),
  });

  if (fetching) return <LoadingState message="Loading cluster..." />;

  if (error) {
    return (
      <ErrorState
        message={error.message}
        onRetry={() => reexecute({ requestPolicy: "network-only" })}
      />
    );
  }

  if (!cluster) {
    return <ErrorState message="Cluster not found" />;
  }

  return (
    <PageLayout
      title={cluster.name}
      breadcrumbs={[
        { label: "Settings", href: "/settings" },
        { label: cluster.name },
      ]}
      actions={
        <AutoRefreshIndicator
          enabled={autoRefresh.enabled}
          onToggle={autoRefresh.setEnabled}
          lastRefreshedAt={autoRefresh.lastRefreshedAt}
          onRefreshNow={autoRefresh.refreshNow}
        />
      }
    >
      <div className="mb-6 space-y-1">
        <p className="text-xs text-muted-foreground font-mono">{cluster.id}</p>
        <div className="flex gap-4 text-xs text-muted-foreground">
          <span>Created: {formatDate(cluster.createdOn)}</span>
          {cluster.updatedOn && (
            <span>Updated: {formatDate(cluster.updatedOn)}</span>
          )}
        </div>
      </div>

      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-base">Configuration</CardTitle>
        </CardHeader>
        <CardContent>
          <ConfigSection config={cluster.config ?? {}} />
        </CardContent>
      </Card>

      <section>
        <h2 className="text-lg font-semibold mb-4">Environments</h2>
        {cluster.environments.length === 0 ? (
          <EmptyState
            title="No environments"
            description="No environments have been created in this cluster yet."
          />
        ) : (
          <div className="rounded-md border">
            <table className="w-full">
              <thead>
                <tr className="border-b bg-muted/50">
                  <th className="px-4 py-3 text-left text-sm font-medium">
                    Name
                  </th>
                </tr>
              </thead>
              <tbody>
                {cluster.environments.map((env) => (
                  <tr
                    key={env.id}
                    className="border-b last:border-0 hover:bg-muted/30 transition-colors"
                  >
                    <td className="px-4 py-3 text-sm">
                      <Link
                        to={`/environments/${env.id}`}
                        className="font-medium hover:underline"
                      >
                        {env.name}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </PageLayout>
  );
}
