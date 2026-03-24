import { Link } from "react-router";
import { useListClustersQuery } from "@/generated/graphql";
import { PageLayout } from "@/components/PageLayout";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Database } from "lucide-react";
import { CreateClusterDialog } from "./CreateClusterDialog";

function ConfigSummary({ config }: { config: Record<string, unknown> }) {
  const items: string[] = [];
  if (config.ingress_class) items.push(`Ingress: ${config.ingress_class}`);
  if (config.db_size) items.push(`DB: ${config.db_size}`);
  if (config.fqdn_suffix) items.push(`FQDN: ${config.fqdn_suffix}`);
  if (config.runtime_class) items.push(`Runtime: ${config.runtime_class}`);
  if (config.dedicated_ingress) items.push("Dedicated Ingress");
  if (config.standard_storage) items.push("Standard Storage");

  if (items.length === 0) return null;

  return (
    <p className="text-xs text-muted-foreground mt-1">{items.join(" · ")}</p>
  );
}

export default function SettingsPage() {
  const [{ data, fetching, error }, reexecute] = useListClustersQuery();

  const refresh = () => reexecute({ requestPolicy: "network-only" });

  return (
    <PageLayout title="Settings" breadcrumbs={[{ label: "Settings" }]}>
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Clusters</h2>
          <CreateClusterDialog onCreated={refresh} />
        </div>

        {fetching && <LoadingState message="Loading clusters..." />}

        {error && <ErrorState message={error.message} onRetry={refresh} />}

        {data && data.clusters.length === 0 && (
          <EmptyState
            title="No clusters"
            description="No clusters have been configured yet. Create one to get started."
          />
        )}

        {data && data.clusters.length > 0 && (
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {data.clusters.map((cluster) => (
              <Link
                key={cluster.id}
                to={`/settings/clusters/${cluster.id}`}
                className="block"
              >
                <Card className="cursor-pointer hover:border-primary/50 transition-colors">
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
                    {cluster.config && (
                      <ConfigSummary config={cluster.config} />
                    )}
                  </CardContent>
                </Card>
              </Link>
            ))}
          </div>
        )}
      </section>
    </PageLayout>
  );
}
