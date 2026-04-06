import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { useListEnvironmentsQuery } from "@/generated/graphql";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { StatusBadge } from "@/components/StatusBadge";
import { ThemeToggle } from "@/components/ThemeToggle";
import { AutoRefreshIndicator } from "@/components/AutoRefreshIndicator";
import { CreateEnvironmentDialog } from "./CreateEnvironmentDialog";

export default function EnvironmentListPage() {
  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(true);
  const { data, isLoading, error, refetch, dataUpdatedAt } =
    useListEnvironmentsQuery(undefined, {
      refetchInterval: autoRefreshEnabled ? 10_000 : false,
    });

  return (
    <div className="flex flex-col gap-7 p-8 px-10">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex flex-col gap-1">
          <h1 className="text-[22px] font-semibold tracking-tight text-foreground">
            Environments
          </h1>
          <p className="text-[13px] text-muted-foreground">
            Manage your deployment environments across clusters
          </p>
        </div>
        <div className="flex items-center gap-3">
          <AutoRefreshIndicator
            enabled={autoRefreshEnabled}
            onToggle={setAutoRefreshEnabled}
            lastRefreshedAt={dataUpdatedAt ? new Date(dataUpdatedAt) : null}
            onRefreshNow={() => refetch()}
          />
          <ThemeToggle />
          <CreateEnvironmentDialog onCreated={() => refetch()} />
        </div>
      </div>

      {isLoading && <LoadingState message="Loading environments..." />}
      {error && (
        <ErrorState message={error.message} onRetry={() => refetch()} />
      )}

      {data && data.environments.length === 0 && (
        <EmptyState
          title="No environments"
          description="No environments have been configured yet."
        />
      )}

      {data && data.environments.length > 0 && (
        <>
          {/* Environment Cards */}
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
            {data.environments.map((env) => (
              <Link
                key={env.id}
                to="/environments/$environmentId"
                params={{ environmentId: env.id }}
              >
                <div className="flex flex-col gap-4 rounded-xl border border-border bg-card p-5 transition-colors hover:border-primary/30 cursor-pointer">
                  {/* Name + Status */}
                  <div className="flex items-start justify-between">
                    <div className="flex flex-col gap-1">
                      <span className="text-[15px] font-semibold text-card-foreground tracking-tight">
                        {env.name}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {env.cluster.name} cluster
                      </span>
                    </div>
                    <StatusBadge
                      status={env.deployments.length > 0 ? "ACTIVE" : "PENDING"}
                    />
                  </div>

                  {/* Stats */}
                  <div className="flex gap-6">
                    <div className="flex flex-col gap-0.5">
                      <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
                        Apps
                      </span>
                      <span className="text-lg font-semibold text-card-foreground">
                        {env.deployments.length}
                      </span>
                    </div>
                  </div>

                  {/* Footer */}
                  <div className="border-t border-border pt-4">
                    <div className="flex items-center justify-between">
                      <span className="text-[11px] text-muted-foreground">
                        {env.deployments.length} deployment
                        {env.deployments.length !== 1 ? "s" : ""}
                      </span>
                      {env.deployments.length > 0 && (
                        <div className="flex gap-1">
                          {env.deployments.slice(0, 3).map((d) => (
                            <StatusBadge key={d.id} status={d.status} />
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </Link>
            ))}
          </div>

          {/* Recent Activity */}
          <div className="flex flex-col gap-3">
            <span className="text-sm font-semibold text-foreground">
              Recent Activity
            </span>
            {/* Table header */}
            <div className="flex items-center gap-4 px-4 py-2">
              <span className="w-[200px] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                Environment
              </span>
              <span className="w-[180px] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                Application
              </span>
              <span className="w-[100px] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                Status
              </span>
              <span className="flex-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                Version
              </span>
            </div>
            {/* Table rows - show deployments across all envs */}
            {data.environments
              .flatMap((env) =>
                env.deployments.map((d) => ({
                  envName: env.name,
                  envId: env.id,
                  ...d,
                })),
              )
              .slice(0, 5)
              .map((d, i) => (
                <Link
                  key={d.id}
                  to="/environments/$environmentId/deployments/$deploymentId"
                  params={{
                    environmentId: d.envId,
                    deploymentId: d.id,
                  }}
                >
                  <div
                    className={`flex items-center gap-4 rounded-lg px-4 py-3 transition-colors hover:bg-accent/50 ${
                      i % 2 === 0 ? "bg-surface" : ""
                    }`}
                  >
                    <span className="w-[200px] text-[13px] font-medium text-foreground">
                      {d.envName}
                    </span>
                    <span className="w-[180px] text-[13px] text-muted-foreground">
                      {d.name}
                    </span>
                    <div className="w-[100px]">
                      <StatusBadge status={d.status} />
                    </div>
                    <span className="flex-1 font-mono text-[13px] text-muted-foreground">
                      {d.applicationVersion}
                    </span>
                  </div>
                </Link>
              ))}
          </div>
        </>
      )}
    </div>
  );
}
