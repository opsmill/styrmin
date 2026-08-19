/**
 * Clones tab on the environment detail page (010-environment-clone, US4).
 *
 * A clone is asynchronous and can partially fail, so the record — not the
 * resulting environment — is the operator's source of truth. This section is
 * that record made visible: the derived status, 100% per-source-deployment
 * attribution (SC-003), the provenance links, and the operation-level events.
 *
 * Two properties of the backend surface shape everything here:
 *
 * - **Status is derived on every read, never stored** (FR-009), so the list
 *   converges purely by refetching. It also means a *just created* clone can
 *   already read `IN_PROGRESS` — an upfront skip counts as recorded progress —
 *   so nothing assumes a PENDING-first progression.
 * - **Discarding the created environment through ordinary environment deletion
 *   is the supported discard path** (SC-005), and it drives the clone to
 *   `FAILED` with a `created_environment_deleted` event. That is a deliberate
 *   operator action, not a malfunction, so the row labels it *Discarded*
 *   instead of presenting a bare failure.
 */
import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { ChevronDown, ChevronRight } from "lucide-react";

import {
  useGetEnvironmentCloneQuery,
  useListEnvironmentClonesQuery,
  type EnvironmentCloneStatus,
  type GetEnvironmentCloneQuery,
  type ListEnvironmentClonesQuery,
} from "@/generated/graphql";
import { StatusBadge, getStatusColor } from "@/components/StatusBadge";
import { ErrorState } from "@/components/ErrorState";
import {
  CloneEnvironmentDialog,
  type CloneCandidateDeployment,
} from "./CloneEnvironmentDialog";

/** One clone as returned by `ListEnvironmentClones`. */
export type EnvironmentCloneItem =
  ListEnvironmentClonesQuery["environmentClones"][number];

/** One source deployment's outcome, list projection. */
export type EnvironmentCloneResultItem =
  EnvironmentCloneItem["deploymentResults"][number];

/** The full single-clone record, as returned by `GetEnvironmentClone`. */
export type EnvironmentCloneDetail =
  GetEnvironmentCloneQuery["environmentClone"];

/**
 * Poll interval for the clones list and for an expanded clone's detail. Matches
 * the Backups tab: both statuses are derived on every read, so refetching is
 * the only thing that moves them.
 */
const REFRESH_INTERVAL_MS = 10_000;

/**
 * Statuses at which a clone stops changing on its own. Polling is pointless
 * once every listed clone is terminal, so the interval is dropped rather than
 * left running against records that can no longer move.
 */
const TERMINAL_CLONE_STATUSES: readonly EnvironmentCloneStatus[] = [
  "COMPLETED",
  "PARTIAL",
  "FAILED",
];

/** Whether a derived clone status can still change on its own. */
export function isCloneTerminal(status: EnvironmentCloneStatus): boolean {
  return TERMINAL_CLONE_STATUSES.includes(status);
}

/**
 * Poll interval for the clones list, or `false` to stop polling.
 *
 * Three gates, all of which must be open:
 *
 * - **`isActive`** — the Clones tab is the one on screen. `TabPanel` unmounts
 *   inactive panels today, but the polling contract is stated explicitly rather
 *   than inherited from that (tab-scoped-polling guideline).
 * - **`autoRefreshEnabled`** — the page's `AutoRefreshIndicator` would be lying
 *   if a paused page kept requesting.
 * - **at least one non-terminal clone** — a list of finished clones has nothing
 *   left to converge to. The clone mutation invalidates this query key, so a
 *   newly started clone re-arms the interval on the spot.
 *
 * `undefined` clones (first render, before any data) counts as "nothing to
 * poll for": the initial fetch is driven by `enabled`, not by the interval.
 */
export function cloneListRefetchInterval({
  isActive,
  autoRefreshEnabled,
  clones,
}: {
  isActive: boolean;
  autoRefreshEnabled: boolean;
  clones: readonly { status: EnvironmentCloneStatus }[] | undefined;
}): number | false {
  if (!isActive || !autoRefreshEnabled) return false;
  const anyNonTerminal =
    clones?.some((clone) => !isCloneTerminal(clone.status)) ?? false;
  return anyNonTerminal ? REFRESH_INTERVAL_MS : false;
}

/**
 * The `clone_errors` step prefix written when the created environment is
 * deleted through ordinary environment deletion — the documented discard path.
 * `cloneErrors` entries arrive pre-rendered as `"step: error"`.
 */
const DISCARD_STEP_PREFIX = "created_environment_deleted:";

/**
 * Whether this clone was discarded by deleting the environment it created.
 *
 * Detected from the recorded event rather than from `createdEnvironment` being
 * null, because null also means "not materialised yet" — the two must not read
 * the same on screen.
 */
export function isCloneDiscarded(cloneErrors: readonly string[]): boolean {
  return cloneErrors.some((entry) => entry.startsWith(DISCARD_STEP_PREFIX));
}

export interface CloneResultSummary {
  total: number;
  cloned: number;
  skipped: number;
  failed: number;
  pending: number;
}

/** Fold the per-deployment outcomes into the counts the collapsed row shows. */
export function summariseCloneResults(
  results: readonly { outcome: string }[],
): CloneResultSummary {
  const summary: CloneResultSummary = {
    total: results.length,
    cloned: 0,
    skipped: 0,
    failed: 0,
    pending: 0,
  };
  for (const result of results) {
    switch (result.outcome) {
      case "CLONED":
        summary.cloned += 1;
        break;
      case "SKIPPED":
        summary.skipped += 1;
        break;
      case "FAILED":
        summary.failed += 1;
        break;
      default:
        summary.pending += 1;
    }
  }
  return summary;
}

/**
 * One-liner for the Applications column, e.g. `1/3 cloned · 1 skipped,
 * 1 failed`. Every non-cloned bucket is spelled out so a `PARTIAL` clone says
 * why on the collapsed row.
 */
export function formatCloneResultSummary(summary: CloneResultSummary): string {
  if (summary.total === 0) return "Config only";

  const detail: string[] = [];
  if (summary.skipped > 0) detail.push(`${summary.skipped} skipped`);
  if (summary.failed > 0) detail.push(`${summary.failed} failed`);
  if (summary.pending > 0) detail.push(`${summary.pending} pending`);

  const base = `${summary.cloned}/${summary.total} cloned`;
  return detail.length > 0 ? `${base} · ${detail.join(", ")}` : base;
}

/**
 * Coarse relative age of an ISO timestamp.
 *
 * Local to this section rather than shared: the environment detail page keeps
 * an identical private helper for its deployment rows, and promoting one to
 * `src/lib/` is a cross-page refactor this feature has no need to make.
 */
export function relativeAge(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.max(0, Math.floor((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

// ---------------------------------------------------------------------------
// Expanded detail
// ---------------------------------------------------------------------------

interface CloneDeploymentResultsProps {
  clone: EnvironmentCloneDetail;
}

/**
 * The per-source-deployment attribution list (SC-003).
 *
 * Every source deployment the clone considered appears exactly once, with its
 * reason rendered verbatim: the reason vocabulary is open-ended
 * (`not_selected`, `not_eligible`, `internal`, `capture_failed`,
 * `driver_version_gone`, …) and the backend is free to add to it, so it is
 * shown as text rather than switched on.
 */
function CloneDeploymentResults({ clone }: CloneDeploymentResultsProps) {
  if (clone.deploymentResults.length === 0) {
    return (
      <p
        className="text-sm text-muted-foreground"
        data-testid="environment-clone-results-empty"
      >
        Config-only clone — no applications were considered
      </p>
    );
  }

  const createdEnvironmentId = clone.createdEnvironment?.id ?? null;

  return (
    <ul className="flex flex-col gap-1" data-testid="environment-clone-results">
      {clone.deploymentResults.map((result) => (
        <li
          key={result.deploymentId}
          className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"
          data-testid="environment-clone-result"
          data-deployment-id={result.deploymentId}
          data-deployment-name={result.deploymentName}
          data-outcome={result.outcome}
          data-reason={result.reason ?? ""}
          data-counterpart-deployment-id={result.counterpartDeploymentId ?? ""}
          data-restore-id={result.restoreId ?? ""}
        >
          <span className="font-medium text-foreground">
            {result.deploymentName}
          </span>
          <span>{result.outcome.toLowerCase()}</span>
          {result.reason && <span>— {result.reason}</span>}
          {result.counterpartDeploymentId &&
            (createdEnvironmentId ? (
              <Link
                to="/environments/$environmentId/deployments/$deploymentId"
                params={{
                  environmentId: createdEnvironmentId,
                  deploymentId: result.counterpartDeploymentId,
                }}
                className="underline hover:text-foreground"
                data-testid="environment-clone-counterpart-link"
              >
                view counterpart
              </Link>
            ) : (
              // The counterpart id outlives the environment it lived in: once
              // the clone is discarded there is nothing to navigate to, so the
              // id is shown as history instead of as a dead link.
              <span data-testid="environment-clone-counterpart-gone">
                counterpart {result.counterpartDeploymentId} no longer reachable
              </span>
            ))}
        </li>
      ))}
    </ul>
  );
}

interface CloneInputsProps {
  clone: EnvironmentCloneDetail;
}

/** The request as it was submitted — the inputs that produced this outcome. */
function CloneInputs({ clone }: CloneInputsProps) {
  return (
    <dl
      className="grid grid-cols-[160px_1fr] gap-x-3 gap-y-1 text-xs"
      data-testid="environment-clone-inputs"
    >
      <dt className="text-muted-foreground">Cloned from</dt>
      <dd className="text-foreground" data-testid="environment-clone-source">
        {clone.sourceEnvironment ? (
          <Link
            to="/environments/$environmentId"
            params={{ environmentId: clone.sourceEnvironment.id }}
            className="underline hover:text-foreground"
          >
            {clone.sourceEnvironment.name}
          </Link>
        ) : (
          // FR: provenance survives the source's deletion — the denormalised
          // name is still readable when the link is gone.
          <span>{clone.sourceEnvironmentName} (deleted)</span>
        )}
      </dd>

      <dt className="text-muted-foreground">Applications requested</dt>
      <dd
        className="text-foreground"
        data-testid="environment-clone-requested-deployments"
      >
        {clone.requestedDeploymentIds == null
          ? "all eligible"
          : clone.requestedDeploymentIds.length === 0
            ? "none (configuration only)"
            : `${clone.requestedDeploymentIds.length} selected`}
      </dd>

      <dt className="text-muted-foreground">Config override</dt>
      <dd
        className="font-mono text-foreground break-all"
        data-testid="environment-clone-config-override"
      >
        {clone.configOverride ? JSON.stringify(clone.configOverride) : "none"}
      </dd>

      <dt className="text-muted-foreground">Cleared fields</dt>
      <dd
        className="font-mono text-foreground"
        data-testid="environment-clone-clear-fields"
      >
        {clone.clearConfigFields && clone.clearConfigFields.length > 0
          ? clone.clearConfigFields.join(", ")
          : "none"}
      </dd>
    </dl>
  );
}

// ---------------------------------------------------------------------------
// Row
// ---------------------------------------------------------------------------

interface EnvironmentCloneRowProps {
  clone: EnvironmentCloneItem;
  /** Row position, used only for zebra striping. */
  index: number;
  /** Mirrors the page-level auto-refresh toggle. */
  autoRefreshEnabled: boolean;
}

/**
 * One clone in the list, with its full record behind an expand toggle.
 *
 * The collapsed row is fed entirely by the list query and the expanded panel
 * entirely by `GetEnvironmentClone`, so the two can never show contradicting
 * projections of the same clone. `data-*` attributes publish identity, derived
 * status and the attribution counts so the Playwright scenario driver reports
 * the same strings the SDK driver reads off GraphQL.
 */
function EnvironmentCloneRow({
  clone,
  index,
  autoRefreshEnabled,
}: EnvironmentCloneRowProps) {
  const [expanded, setExpanded] = useState(false);

  const summary = summariseCloneResults(clone.deploymentResults);
  const terminal = isCloneTerminal(clone.status);
  const discarded = isCloneDiscarded(clone.cloneErrors);
  const colors = getStatusColor(clone.status.toLowerCase());

  const detailQuery = useGetEnvironmentCloneQuery(
    { environmentCloneId: clone.id },
    {
      enabled: expanded,
      // A non-terminal clone's detail moves under the operator (restores land,
      // counterparts appear), so it polls on the same interval as the list —
      // and stops for good once the record is terminal.
      refetchInterval:
        expanded && autoRefreshEnabled && !terminal
          ? REFRESH_INTERVAL_MS
          : false,
    },
  );
  const detail = detailQuery.data?.environmentClone;

  return (
    <div
      data-testid="environment-clone-row"
      data-environment-clone-id={clone.id}
      data-environment-clone-name={clone.name}
      data-environment-clone-status={clone.status}
      data-environment-clone-discarded={discarded}
      data-created-environment-id={clone.createdEnvironment?.id ?? ""}
      data-environment-backup-id={clone.environmentBackup?.id ?? ""}
      data-result-total={summary.total}
      data-result-cloned={summary.cloned}
      data-result-skipped={summary.skipped}
      data-result-failed={summary.failed}
      data-result-pending={summary.pending}
    >
      <div
        className={`flex items-center gap-4 rounded-lg border-l-[3px] px-4 py-3 ${colors.border} ${
          index % 2 === 0 ? "bg-surface" : ""
        }`}
      >
        <div className="flex w-[220px] items-center gap-2">
          <button
            type="button"
            className="flex-shrink-0 text-muted-foreground hover:text-foreground"
            data-testid="environment-clone-expand-button"
            aria-expanded={expanded}
            aria-label={
              expanded
                ? `Hide details of clone ${clone.name}`
                : `Show details of clone ${clone.name}`
            }
            onClick={() => setExpanded((open) => !open)}
          >
            {expanded ? (
              <ChevronDown className="h-4 w-4" />
            ) : (
              <ChevronRight className="h-4 w-4" />
            )}
          </button>
          <div className={`h-2 w-2 flex-shrink-0 rounded-full ${colors.dot}`} />
          <span className="truncate text-[13px] font-medium text-foreground">
            {clone.name}
          </span>
        </div>
        <div className="w-[110px]" data-testid="environment-clone-status">
          <StatusBadge status={clone.status.toLowerCase()} />
        </div>
        <span
          className="w-[200px] text-[13px] text-muted-foreground"
          data-testid="environment-clone-applications"
        >
          {formatCloneResultSummary(summary)}
        </span>
        <span
          className="w-[180px] text-[13px] text-muted-foreground"
          data-testid="environment-clone-environment"
        >
          {clone.createdEnvironment ? (
            <Link
              to="/environments/$environmentId"
              params={{ environmentId: clone.createdEnvironment.id }}
              className="underline hover:text-foreground"
              data-testid="environment-clone-environment-link"
            >
              {clone.createdEnvironment.name}
            </Link>
          ) : discarded ? (
            <span data-testid="environment-clone-discarded">Discarded</span>
          ) : (
            <span data-testid="environment-clone-environment-pending">
              not created yet
            </span>
          )}
        </span>
        <span
          className="flex-1 text-[13px] text-muted-foreground"
          data-testid="environment-clone-age"
          title={new Date(clone.createdOn).toLocaleString()}
        >
          {relativeAge(clone.createdOn)}
        </span>
      </div>

      {discarded && (
        <p
          className="px-4 pb-1 text-xs text-muted-foreground"
          data-testid="environment-clone-discard-note"
        >
          The environment this clone created was deleted, which is the supported
          way to discard a clone. The record is kept as history and the name is
          free to clone into again.
        </p>
      )}

      {expanded && (
        <div
          className="flex flex-col gap-3 px-4 py-3"
          data-testid="environment-clone-detail"
        >
          <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Backing capture
          </span>
          <span
            className="text-xs text-muted-foreground"
            data-testid="environment-clone-backup"
          >
            {clone.environmentBackup
              ? `${clone.environmentBackup.name} (${clone.environmentBackup.status.toLowerCase()}) — on the Backups tab of this environment`
              : "no longer available"}
          </span>

          {detailQuery.isError ? (
            <p
              className="text-sm text-destructive"
              data-testid="environment-clone-detail-error"
            >
              {(detailQuery.error as Error).message}
            </p>
          ) : detail === undefined ? (
            <p className="text-sm text-muted-foreground">
              Loading clone details...
            </p>
          ) : (
            <>
              <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                Applications in this clone
              </span>
              <CloneDeploymentResults clone={detail} />

              <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                Request
              </span>
              <CloneInputs clone={detail} />

              {detail.cloneErrors.length > 0 && (
                <>
                  <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                    Events
                  </span>
                  <ul
                    className="flex flex-col gap-1"
                    data-testid="environment-clone-errors"
                  >
                    {detail.cloneErrors.map((entry) => (
                      <li
                        key={entry}
                        className="text-xs text-muted-foreground"
                        data-testid="environment-clone-error-entry"
                      >
                        {entry}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section
// ---------------------------------------------------------------------------

export interface EnvironmentClonesSectionProps {
  environmentId: string;
  environmentName: string;
  /** Source deployments for the dialog's picker. */
  deployments: readonly CloneCandidateDeployment[];
  /** Source environment config — the dialog's clear-field candidates. */
  config?: Record<string, unknown> | null;
  /**
   * Whether the Clones tab is the active tab. Gates both `enabled` and
   * `refetchInterval`, per the tab-scoped-polling guideline: the panel is
   * unmounted while inactive today, but relying on that leaves the polling
   * contract implicit.
   */
  isActive: boolean;
  /** Mirrors the environment detail page's auto-refresh toggle. */
  autoRefreshEnabled: boolean;
}

/**
 * Clones of this environment, newest first, with the ADMIN-only clone action.
 *
 * Scoped by *source* environment: these are the clones taken **of** this
 * environment. An environment that was itself produced by a clone carries that
 * provenance on the clone record of its source, not here.
 */
export function EnvironmentClonesSection({
  environmentId,
  environmentName,
  deployments,
  config,
  isActive,
  autoRefreshEnabled,
}: EnvironmentClonesSectionProps) {
  const query = useListEnvironmentClonesQuery(
    { environmentId },
    {
      enabled: isActive,
      // Function form so the interval can key on the data this same query
      // returned — see `cloneListRefetchInterval`.
      refetchInterval: (polled) =>
        cloneListRefetchInterval({
          isActive,
          autoRefreshEnabled,
          clones: polled.state.data?.environmentClones,
        }),
    },
  );

  const clones = query.data?.environmentClones ?? [];

  return (
    <div
      className="flex flex-col gap-4"
      data-testid="environment-clones-section"
      data-environment-id={environmentId}
    >
      <div className="flex items-start justify-between gap-6">
        <div className="flex flex-col gap-1">
          <span className="text-[13px] font-semibold text-foreground">
            Environment Clones
          </span>
          <span className="text-xs text-muted-foreground">
            Each clone captures a fresh environment backup of this environment
            and builds a new environment from it. This environment is never
            modified.
          </span>
        </div>
        <CloneEnvironmentDialog
          environmentId={environmentId}
          environmentName={environmentName}
          deployments={deployments}
          config={config}
        />
      </div>

      {query.isError ? (
        <ErrorState
          title="Couldn't load environment clones"
          message={(query.error as Error).message}
          onRetry={() => {
            void query.refetch();
          }}
        />
      ) : query.isLoading ? (
        <p className="text-sm text-muted-foreground">Loading clones...</p>
      ) : clones.length === 0 ? (
        <p
          className="text-sm text-muted-foreground"
          data-testid="environment-clones-empty"
        >
          No clones of this environment yet
        </p>
      ) : (
        <>
          {/* Table header */}
          <div className="flex items-center gap-4 px-4 py-2">
            <span className="w-[220px] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Name
            </span>
            <span className="w-[110px] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Status
            </span>
            <span className="w-[200px] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Applications
            </span>
            <span className="w-[180px] text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Environment
            </span>
            <span className="flex-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Started
            </span>
          </div>
          {clones.map((clone, i) => (
            <EnvironmentCloneRow
              key={clone.id}
              clone={clone}
              index={i}
              autoRefreshEnabled={autoRefreshEnabled}
            />
          ))}
        </>
      )}
    </div>
  );
}
