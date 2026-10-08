import { useMemo, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { useListDriversQuery } from "@/generated/graphql";
import { PageLayout } from "@/components/PageLayout";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { IfRole } from "@/auth/IfRole";
import { useEffectiveRole } from "@/auth/useEffectiveRole";
import { useDebounce } from "@/hooks/useDebounce";
import { LoadDriverDrawer } from "@/pages/drivers/LoadDriverDrawer";
import { LatestBadge } from "@/pages/drivers/VersionStatusBadge";
import { DriverLogo } from "@/pages/drivers/DriverLogo";
import { highlightMatch } from "@/lib/highlight";
import { collidingVersions, displayDriverVersion } from "@/lib/driverVersion";
import { cn } from "@/lib/utils";
import { formatRelativeTime } from "@/pages/drivers/driver-detail/relative-time";
import {
  type DriverListVersion,
  type FilteredDriver,
  filterDrivers,
  flattenVersions,
  showsLatestBadge,
  versionSource,
} from "@/pages/drivers/lib/driverList";
import { Plus, Search, X } from "lucide-react";
import { useDocumentTitle } from "@/hooks/use-document-title";

type ViewMode = "grouped" | "flat";

export default function DriverListPage() {
  useDocumentTitle("Drivers");
  const navigate = useNavigate();
  const effectiveRole = useEffectiveRole();
  const canWrite = effectiveRole === "READ_WRITE" || effectiveRole === "ADMIN";

  const [viewMode, setViewMode] = useState<ViewMode>("grouped");
  const [rawQuery, setRawQuery] = useState("");
  const [loadOpen, setLoadOpen] = useState(false);
  const query = useDebounce(rawQuery, 200);

  const { data, isLoading, error, refetch } = useListDriversQuery();

  const filtered = useMemo(
    () => (data ? filterDrivers(data.applicationDrivers, query) : []),
    [data, query],
  );

  const openVersion = (driverId: string, versionId: string) =>
    navigate({
      to: "/drivers/$driverId",
      params: { driverId },
      search: { version: versionId },
    });

  const hasAnyDrivers = !!data && data.applicationDrivers.length > 0;

  return (
    <PageLayout
      title="Drivers"
      breadcrumbs={[{ label: "Drivers" }]}
      actions={
        <IfRole minimum="READ_WRITE">
          <Button onClick={() => setLoadOpen(true)}>
            <Plus className="h-4 w-4" />
            Load driver
          </Button>
        </IfRole>
      }
    >
      <LoadDriverDrawer open={loadOpen} onOpenChange={setLoadOpen} />

      {isLoading && <LoadingState message="Loading drivers..." />}

      {error && (
        <ErrorState message={error.message} onRetry={() => refetch()} />
      )}

      {data && !hasAnyDrivers && (
        <EmptyState
          icon="package"
          title="No drivers loaded yet"
          description="A driver tells Styrmin how to deploy, back up and upgrade an application. Load one from a Git repository or a local directory to get started."
          actionLabel={canWrite ? "Load driver" : undefined}
          onAction={canWrite ? () => setLoadOpen(true) : undefined}
        />
      )}

      {hasAnyDrivers && (
        <div className="space-y-4">
          <Toolbar
            viewMode={viewMode}
            onViewModeChange={setViewMode}
            query={rawQuery}
            onQueryChange={setRawQuery}
          />

          {filtered.length === 0 ? (
            <NoMatches query={query} onClear={() => setRawQuery("")} />
          ) : viewMode === "grouped" ? (
            <div className="space-y-3">
              {filtered.map((driver) => (
                <AppGroup
                  key={driver.id}
                  driver={driver}
                  query={query}
                  onOpen={openVersion}
                />
              ))}
            </div>
          ) : (
            <FlatTable drivers={filtered} query={query} onOpen={openVersion} />
          )}
        </div>
      )}
    </PageLayout>
  );
}

function Toolbar({
  viewMode,
  onViewModeChange,
  query,
  onQueryChange,
}: {
  viewMode: ViewMode;
  onViewModeChange: (v: ViewMode) => void;
  query: string;
  onQueryChange: (q: string) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex items-center gap-1 rounded-lg border border-border bg-muted/40 p-0.5">
        <SegButton
          active={viewMode === "grouped"}
          onClick={() => onViewModeChange("grouped")}
        >
          Group by application
        </SegButton>
        <SegButton
          active={viewMode === "flat"}
          onClick={() => onViewModeChange("flat")}
        >
          Flat list
        </SegButton>
      </div>

      <div className="relative ml-auto w-full sm:w-72">
        <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
        <Input
          value={query}
          onChange={(e) => onQueryChange(e.target.value)}
          placeholder="Filter drivers..."
          className="pl-8 pr-8"
          aria-label="Filter drivers"
        />
        {query && (
          <button
            type="button"
            onClick={() => onQueryChange("")}
            aria-label="Clear filter"
            className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
    </div>
  );
}

function SegButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "rounded-md px-3 py-1 text-[13px] font-medium transition-colors",
        active
          ? "bg-background text-foreground shadow-sm"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {children}
    </button>
  );
}

const GRID_COLS =
  "grid grid-cols-[minmax(140px,1fr)_minmax(180px,1.4fr)_minmax(120px,1fr)_110px] gap-4";

function SourceBadge({ sourceType }: { sourceType: string }) {
  return (
    <Badge variant="secondary" className="shrink-0">
      {sourceType === "local" ? "Local" : "Git"}
    </Badge>
  );
}

function SourceCell({
  version,
  query,
}: {
  version: DriverListVersion;
  query: string;
}) {
  return (
    <span className="flex min-w-0 items-center gap-2">
      <SourceBadge sourceType={version.sourceType} />
      <span className="truncate font-mono text-xs text-muted-foreground">
        {highlightMatch(versionSource(version), query)}
      </span>
    </span>
  );
}

function ColumnHeaders() {
  return (
    <div
      className={cn(
        GRID_COLS,
        "border-b border-border/60 px-4 py-2.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground",
      )}
    >
      <span>Driver version</span>
      <span>Source</span>
      <span>Supports app versions</span>
      <span>Loaded</span>
    </div>
  );
}

function VersionRow({
  driver,
  version,
  isLatest,
  colliding,
  query,
  onOpen,
}: {
  driver: FilteredDriver;
  version: DriverListVersion;
  isLatest: boolean;
  colliding: Set<string>;
  query: string;
  onOpen: (driverId: string, versionId: string) => void;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onOpen(driver.id, version.id)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onOpen(driver.id, version.id);
        }
      }}
      className={cn(
        GRID_COLS,
        "cursor-pointer items-center border-b border-border/60 px-4 py-2.5 text-[13px] last:border-b-0 hover:bg-primary/5",
      )}
    >
      <span className="flex items-center gap-2">
        <span className="font-mono text-[13px] font-medium">
          {highlightMatch(displayDriverVersion(version, colliding), query)}
        </span>
        {isLatest && <LatestBadge />}
      </span>
      <SourceCell version={version} query={query} />
      <span className="font-mono text-xs">
        {version.supportedVersions
          ? highlightMatch(version.supportedVersions, query)
          : "—"}
      </span>
      <span className="text-xs text-muted-foreground">
        {formatRelativeTime(version.createdOn)}
      </span>
    </div>
  );
}

function AppGroup({
  driver,
  query,
  onOpen,
}: {
  driver: FilteredDriver;
  query: string;
  onOpen: (driverId: string, versionId: string) => void;
}) {
  const colliding = collidingVersions(driver.versions);
  return (
    <div
      data-testid="driver-group"
      data-driver-name={driver.name}
      className="overflow-hidden rounded-lg border border-border bg-background"
    >
      <div className="flex items-center gap-3 border-b border-border bg-muted/40 px-4 py-3">
        <DriverLogo icon={driver.latestVersion?.icon} size="md" />
        <span className="text-[13.5px] font-semibold">
          {highlightMatch(driver.name, query)}
        </span>
        <span className="ml-auto text-xs text-muted-foreground">
          {driver.versions.length} driver version
          {driver.versions.length !== 1 ? "s" : ""}
        </span>
      </div>
      <ColumnHeaders />
      {driver.versions.map((version) => (
        <VersionRow
          key={version.id}
          driver={driver}
          version={version}
          isLatest={showsLatestBadge(driver, version)}
          colliding={colliding}
          query={query}
          onOpen={onOpen}
        />
      ))}
    </div>
  );
}

function FlatTable({
  drivers,
  query,
  onOpen,
}: {
  drivers: FilteredDriver[];
  query: string;
  onOpen: (driverId: string, versionId: string) => void;
}) {
  const rows = useMemo(() => flattenVersions(drivers), [drivers]);
  const collidingByDriver = useMemo(
    () => new Map(drivers.map((d) => [d.id, collidingVersions(d.versions)])),
    [drivers],
  );
  return (
    <div className="overflow-hidden rounded-lg border border-border bg-background">
      <div
        className={cn(
          GRID_COLS,
          "border-b border-border/60 px-4 py-2.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground",
        )}
      >
        <span>Driver</span>
        <span>Source</span>
        <span>Supports app versions</span>
        <span>Loaded</span>
      </div>
      {rows.map(({ driver, version, isLatest }) => (
        <div
          key={version.id}
          role="button"
          tabIndex={0}
          onClick={() => onOpen(driver.id, version.id)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              onOpen(driver.id, version.id);
            }
          }}
          className={cn(
            GRID_COLS,
            "cursor-pointer items-center border-b border-border/60 px-4 py-2.5 text-[13px] last:border-b-0 hover:bg-primary/5",
          )}
        >
          <span className="flex items-center gap-2">
            <DriverLogo icon={version.icon} size="sm" />
            <span className="font-medium">
              {highlightMatch(driver.name, query)}
            </span>
            <span className="font-mono text-xs text-muted-foreground">
              {highlightMatch(
                displayDriverVersion(
                  version,
                  collidingByDriver.get(driver.id) ?? new Set(),
                ),
                query,
              )}
            </span>
            {isLatest && <LatestBadge />}
          </span>
          <SourceCell version={version} query={query} />
          <span className="font-mono text-xs">
            {version.supportedVersions
              ? highlightMatch(version.supportedVersions, query)
              : "—"}
          </span>
          <span className="text-xs text-muted-foreground">
            {formatRelativeTime(version.createdOn)}
          </span>
        </div>
      ))}
    </div>
  );
}

function NoMatches({ query, onClear }: { query: string; onClear: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border py-14 text-center">
      <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-muted">
        <Search className="h-5 w-5 text-muted-foreground" />
      </div>
      <div className="space-y-1">
        <p className="text-[15px] font-medium">No drivers match "{query}"</p>
        <p className="text-[13px] text-muted-foreground">
          Try a different name, or load a new driver from a repository.
        </p>
      </div>
      <Button variant="outline" size="sm" onClick={onClear}>
        Clear filter
      </Button>
    </div>
  );
}
