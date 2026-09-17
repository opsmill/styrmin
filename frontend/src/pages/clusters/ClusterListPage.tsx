import { Link } from "@tanstack/react-router";
import { Database } from "lucide-react";
import { useListClustersQuery } from "@/generated/graphql";
import { PageLayout } from "@/components/PageLayout";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { IfRole } from "@/auth/IfRole";
import { CreateClusterDialog } from "@/pages/settings/CreateClusterDialog";
import { ConfigSummary } from "./ConfigSummary";
import { useDocumentTitle } from "@/hooks/use-document-title";

export default function ClusterListPage() {
  useDocumentTitle("Clusters");
  const { data, isLoading, error, refetch } = useListClustersQuery();

  const refresh = () => {
    refetch();
  };

  const clusters = data?.clusters ?? [];
  const canCreate = clusters.length === 0;

  return (
    <PageLayout
      title="Clusters"
      breadcrumbs={[{ label: "Clusters" }]}
      actions={
        canCreate ? (
          <IfRole minimum="READ_WRITE">
            <CreateClusterDialog onCreated={refresh} />
          </IfRole>
        ) : undefined
      }
    >
      {isLoading && <LoadingState message="Loading clusters..." />}

      {error && <ErrorState message={error.message} onRetry={refresh} />}

      {data && clusters.length === 0 && (
        <EmptyState
          title="No cluster"
          description="No cluster has been configured yet. Create one to get started."
        />
      )}

      {clusters.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {clusters.map((cluster) => (
            <Link
              key={cluster.id}
              to="/clusters/$clusterId"
              params={{ clusterId: cluster.id }}
              className="block"
              data-testid="cluster-card"
              data-cluster-id={cluster.id}
              data-cluster-name={cluster.name}
            >
              <Card className="cursor-pointer hover:border-primary/50 transition-colors h-full">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Database className="h-4 w-4" />
                    {cluster.name}
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-xs text-muted-foreground font-mono">
                    {cluster.id}
                  </p>
                  {cluster.config && <ConfigSummary config={cluster.config} />}
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </PageLayout>
  );
}
