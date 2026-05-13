import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { useListEnvironmentsQuery } from "@/generated/graphql";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { StatusBadge, getStatusColor } from "@/components/StatusBadge";
import { ThemeToggle } from "@/components/ThemeToggle";
import { AutoRefreshIndicator } from "@/components/AutoRefreshIndicator";
import { IfRole } from "@/auth/IfRole";
import { CreateEnvironmentDialog } from "./CreateEnvironmentDialog";

function deriveEnvHealth(deployments: { status: string }[]): string {
  if (deployments.length === 0) return "pending";
  if (deployments.some((d) => d.status === "FAILED" || d.status === "failed"))
    return "failed";
  if (
    deployments.some(
      (d) =>
        d.status === "PENDING" ||
        d.status === "pending" ||
        d.status === "in_progress",
    )
  )
    return "pending";
  return "active";
}

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
          <IfRole minimum="READ_WRITE">
            <CreateEnvironmentDialog onCreated={() => refetch()} />
          </IfRole>
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
            {data.environments.map((env) => {
              const userDeploys = env.deployments.filter((d) => !d.internal);
              const health = deriveEnvHealth(userDeploys);
              const colors = getStatusColor(health);

              return (
                <Link
                  key={env.id}
                  to="/environments/$environmentId"
                  params={{ environmentId: env.id }}
                  data-testid="environment-card"
                  data-environment-id={env.id}
                  data-environment-name={env.name}
                >
                  <div
                    className={`flex flex-col gap-4 rounded-xl border-2 bg-card p-5 transition-colors hover:shadow-md cursor-pointer ${colors.border}`}
                  >
                    {/* Name + Status */}
                    <div className="flex items-start justify-between">
                      <div className="flex flex-col gap-1">
                        <div className="flex items-center gap-2">
                          <div
                            className={`h-2.5 w-2.5 rounded-full ${colors.dot}`}
                          />
                          <span className="text-[15px] font-semibold text-card-foreground tracking-tight">
                            {env.name}
                          </span>
                        </div>
                        <span className="text-xs text-muted-foreground ml-[18px]">
                          {env.cluster.name} cluster
                        </span>
                      </div>
                      <StatusBadge status={health} />
                    </div>

                    {/* Stats */}
                    <div className="flex gap-6">
                      <div className="flex flex-col gap-0.5">
                        <span className="text-[11px] uppercase tracking-wider text-muted-foreground">
                          Apps
                        </span>
                        <span className="text-lg font-semibold text-card-foreground">
                          {userDeploys.length}
                        </span>
                      </div>
                    </div>

                    {/* Footer */}
                    <div className="border-t border-border pt-4">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] text-muted-foreground">
                          {userDeploys.length} deployment
                          {userDeploys.length !== 1 ? "s" : ""}
                        </span>
                        {userDeploys.length > 0 && (
                          <div className="flex gap-1">
                            {userDeploys.slice(0, 5).map((d) => {
                              const dc = getStatusColor(d.status);
                              return (
                                <div
                                  key={d.id}
                                  className={`h-2 w-2 rounded-full ${dc.dot}`}
                                  title={`${d.name}: ${d.status}`}
                                />
                              );
                            })}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                </Link>
              );
            })}
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
            {/* Table rows */}
            {data.environments
              .flatMap((env) =>
                env.deployments
                  .filter((d) => !d.internal)
                  .map((d) => ({
                    envName: env.name,
                    envId: env.id,
                    ...d,
                  })),
              )
              .slice(0, 5)
              .map((d, i) => {
                const dc = getStatusColor(d.status);
                return (
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
                      <div className="flex w-[200px] items-center gap-2">
                        <div
                          className={`h-2 w-2 flex-shrink-0 rounded-full ${dc.dot}`}
                        />
                        <span className="text-[13px] font-medium text-foreground">
                          {d.envName}
                        </span>
                      </div>
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
                );
              })}
          </div>
        </>
      )}
    </div>
  );
}
