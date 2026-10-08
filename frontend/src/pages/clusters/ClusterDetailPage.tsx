import { useState } from "react";
import { useParams, Link } from "@tanstack/react-router";
import { useGetClusterQuery } from "@/generated/graphql";
import { PageLayout } from "@/components/PageLayout";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { AutoRefreshIndicator } from "@/components/AutoRefreshIndicator";
import { useDocumentTitle } from "@/hooks/use-document-title";
import { ClusterConfiguration } from "./ClusterConfiguration";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString();
}

export default function ClusterDetailPage() {
  const { clusterId } = useParams({ from: "/clusters/$clusterId" });
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(true);
  const { data, isLoading, error, refetch, dataUpdatedAt } = useGetClusterQuery(
    { clusterId },
    { refetchInterval: autoRefreshEnabled ? 10_000 : false },
  );

  const cluster = data?.cluster;
  useDocumentTitle(cluster?.name ?? "Cluster");

  if (isLoading) return <LoadingState message="Loading cluster..." />;

  if (error) {
    return <ErrorState message={error.message} onRetry={() => refetch()} />;
  }

  if (!cluster) {
    return <ErrorState message="Cluster not found" />;
  }

  return (
    <PageLayout
      title={cluster.name}
      breadcrumbs={[
        { label: "Clusters", href: "/clusters" },
        { label: cluster.name },
      ]}
      actions={
        <AutoRefreshIndicator
          enabled={autoRefreshEnabled}
          onToggle={setAutoRefreshEnabled}
          lastRefreshedAt={dataUpdatedAt ? new Date(dataUpdatedAt) : null}
          onRefreshNow={() => refetch()}
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

      <section className="mb-6">
        <h2 className="text-lg font-semibold mb-4">Configuration</h2>
        <ClusterConfiguration
          config={cluster.config}
          capabilities={cluster.capabilities}
        />
      </section>

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
                        to="/environments/$environmentId"
                        params={{ environmentId: env.id }}
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
