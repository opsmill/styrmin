import { Link } from "@tanstack/react-router";
import { useListClustersQuery } from "@/generated/graphql";
import { PageLayout } from "@/components/PageLayout";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Database, Users, UsersRound } from "lucide-react";
import { IfRole } from "@/auth/IfRole";
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
  const { data, isLoading, error, refetch } = useListClustersQuery();

  const refresh = () => {
    refetch();
  };

  return (
    <PageLayout title="Settings" breadcrumbs={[{ label: "Settings" }]}>
      <section>
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Cluster</h2>
          {data && data.clusters.length === 0 && (
            <IfRole minimum="READ_WRITE">
              <CreateClusterDialog onCreated={refresh} />
            </IfRole>
          )}
        </div>

        {isLoading && <LoadingState message="Loading cluster..." />}

        {error && <ErrorState message={error.message} onRetry={refresh} />}

        {data && data.clusters.length === 0 && (
          <EmptyState
            title="No cluster"
            description="No cluster has been configured yet. Create one to get started."
          />
        )}

        {data && data.clusters.length > 0 && (
          <Link
            to="/settings/clusters/$clusterId"
            params={{ clusterId: data.clusters[0].id }}
            className="block max-w-xl"
            data-testid="cluster-card"
            data-cluster-id={data.clusters[0].id}
            data-cluster-name={data.clusters[0].name}
          >
            <Card className="cursor-pointer hover:border-primary/50 transition-colors">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Database className="h-4 w-4" />
                  {data.clusters[0].name}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-xs text-muted-foreground font-mono">
                  {data.clusters[0].id}
                </p>
                {data.clusters[0].config && (
                  <ConfigSummary config={data.clusters[0].config} />
                )}
              </CardContent>
            </Card>
          </Link>
        )}
      </section>

      <IfRole minimum="ADMIN">
        <section className="mt-8">
          <h2 className="text-lg font-semibold mb-4">Access</h2>
          <div className="grid gap-4 sm:grid-cols-2 max-w-xl">
            <Link to="/users" className="block" data-testid="users-card">
              <Card className="cursor-pointer hover:border-primary/50 transition-colors">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <Users className="h-4 w-4" />
                    Users
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-xs text-muted-foreground">
                    Manage user accounts, roles, and activation status.
                  </p>
                </CardContent>
              </Card>
            </Link>
            <Link to="/groups" className="block" data-testid="groups-card">
              <Card className="cursor-pointer hover:border-primary/50 transition-colors">
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <UsersRound className="h-4 w-4" />
                    Groups
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  <p className="text-xs text-muted-foreground">
                    Group memberships confer effective roles to users.
                  </p>
                </CardContent>
              </Card>
            </Link>
          </div>
        </section>
      </IfRole>
    </PageLayout>
  );
}
