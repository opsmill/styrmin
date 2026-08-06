import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Archive } from "lucide-react";
import {
  useCreateEnvironmentBackupMutation,
  useListEnvironmentBackupsQuery,
} from "@/generated/graphql";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ErrorState";
import { IfRole } from "@/auth/IfRole";
import { EnvironmentBackupRow } from "./EnvironmentBackupRow";

/**
 * Poll interval for the snapshot list. An environment backup's status is
 * derived from its constituents on every read, so the list converges from
 * `IN_PROGRESS` to a terminal status purely by refetching.
 */
const REFRESH_INTERVAL_MS = 10_000;

interface EnvironmentBackupsTabProps {
  environmentId: string;
  /**
   * Mirrors the environment detail page's auto-refresh toggle. The page renders
   * an `AutoRefreshIndicator` above every tab, so a hardcoded interval here
   * would keep polling after the operator paused refresh — the indicator would
   * be lying.
   */
  autoRefreshEnabled: boolean;
}

/**
 * Backups tab on the environment detail page: trigger one coordinated
 * environment backup and list the resulting snapshots with their derived
 * status.
 *
 * Mounted only while the tab is active (`TabPanel` unmounts inactive panels),
 * so the poll stops on its own when the operator navigates away.
 */
export function EnvironmentBackupsTab({
  environmentId,
  autoRefreshEnabled,
}: EnvironmentBackupsTabProps) {
  const [createError, setCreateError] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const query = useListEnvironmentBackupsQuery(
    { environmentId },
    { refetchInterval: autoRefreshEnabled ? REFRESH_INTERVAL_MS : false },
  );

  // Declared in `onSuccess`, not after `mutateAsync` in the handler, per
  // dev/guidelines/frontend/data-fetching.md — invalidation is the mutation's
  // responsibility.
  const createMutation = useCreateEnvironmentBackupMutation({
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["ListEnvironmentBackups"],
      });
      // The fan-out creates one constituent `Backup` per eligible deployment,
      // which the deployment detail page lists via `ListBackups`.
      void queryClient.invalidateQueries({ queryKey: ["ListBackups"] });
    },
  });

  const environmentBackups = query.data?.environmentBackups ?? [];

  async function handleCreate() {
    setCreateError(null);
    try {
      await createMutation.mutateAsync({ environmentId });
    } catch (err) {
      // Surfaced inline rather than swallowed: a rejected fan-out (for
      // example ALREADY_IN_PROGRESS) is the operator's answer to why no new
      // snapshot appeared.
      console.error("[create-environment-backup] mutation failed", err);
      setCreateError(err instanceof Error ? err.message : "Unknown error");
    }
  }

  return (
    <div
      className="flex flex-col gap-4"
      data-testid="environment-backups-tab"
      data-environment-id={environmentId}
    >
      <div className="flex items-start justify-between gap-6">
        <div className="flex flex-col gap-1">
          <span className="text-[13px] font-semibold text-foreground">
            Environment Backups
          </span>
          <span className="text-xs text-muted-foreground">
            One snapshot captures this environment&apos;s configuration and one
            constituent backup per eligible deployment.
          </span>
        </div>
        <IfRole minimum="READ_WRITE">
          <Button
            size="sm"
            data-testid="create-environment-backup-button"
            disabled={createMutation.isPending}
            onClick={handleCreate}
          >
            <Archive className="h-4 w-4" />
            {createMutation.isPending ? "Creating..." : "Create Backup"}
          </Button>
        </IfRole>
      </div>

      {createError && (
        <Alert variant="destructive" data-testid="environment-backups-error">
          <AlertDescription>{createError}</AlertDescription>
        </Alert>
      )}

      {query.isError ? (
        <ErrorState
          title="Couldn't load environment backups"
          message={(query.error as Error).message}
          onRetry={() => {
            void query.refetch();
          }}
        />
      ) : query.isLoading ? (
        <p className="text-sm text-muted-foreground">
          Loading environment backups...
        </p>
      ) : environmentBackups.length === 0 ? (
        <p
          className="text-sm text-muted-foreground"
          data-testid="environment-backups-empty"
        >
          No environment backups yet
        </p>
      ) : (
        <>
          {/* Table header */}
          <div className="flex items-center gap-4 px-4 py-2">
            <span className="w-[240px] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Name
            </span>
            <span className="w-[110px] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Status
            </span>
            <span className="w-[220px] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Applications
            </span>
            <span className="flex-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Created
            </span>
          </div>
          {environmentBackups.map((environmentBackup, i) => (
            <EnvironmentBackupRow
              key={environmentBackup.id}
              environmentBackup={environmentBackup}
              index={i}
              autoRefreshEnabled={autoRefreshEnabled}
            />
          ))}
        </>
      )}
    </div>
  );
}
