import { useMemo, useState } from "react";
import { useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { Copy, Check } from "lucide-react";
import { useGetDriverQuery } from "@/generated/graphql";
import { PageLayout } from "@/components/PageLayout";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabPanel } from "@/components/ui/tabs";
import {
  Select,
  SelectTrigger,
  SelectContent,
  SelectItem,
} from "@/components/ui/select";
import { LatestBadge, OlderBadge } from "./VersionStatusBadge";
import { Tooltip } from "@/components/ui/tooltip";
import { ParametersTab } from "./driver-detail/tabs/ParametersTab";
import { ComponentsTab } from "./driver-detail/tabs/ComponentsTab";
import { formatRelativeTime } from "./driver-detail/relative-time";
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";
import {
  collidingVersions,
  compareVersionsLatestFirst,
  displayDriverVersion,
  LOADED_SCOPE_NOTE,
} from "@/lib/driverVersion";
import { isPlainObject } from "./driver-detail/json-guards";
import type { DriverVersionDetail } from "./driver-detail/types";
import { useDocumentTitle } from "@/hooks/use-document-title";

type DetailTab = "overview" | "parameters" | "components";

/**
 * Driver detail — a single driver version, addressed by the `?version=<id>`
 * search param (defaults to the newest-by-`createdOn` version).
 *
 * Layout follows the resource-detail pattern common to Terraform Registry,
 * Backstage, Fivetran and Kubernetes dashboards: a persistent header (identity,
 * version switcher, status) over a tabbed body. The Overview tab is a scannable
 * summary — stat tiles + a source panel — with the voluminous parameter and
 * component tables deferred to their own tabs (progressive disclosure).
 */
export default function DriverDetailPage() {
  const { driverId } = useParams({ from: "/drivers/$driverId" });
  const { version: versionParam } = useSearch({ from: "/drivers/$driverId" });
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState<DetailTab>("overview");

  const { data, isLoading, error, refetch } = useGetDriverQuery({
    applicationDriverId: driverId,
  });

  const driver = data?.applicationDriver;
  useDocumentTitle(driver?.name ?? "Driver");
  const versions = useMemo(
    () => [...(driver?.versions ?? [])].sort(compareVersionsLatestFirst),
    [driver?.versions],
  );

  if (isLoading && !data) return <LoadingState message="Loading driver..." />;
  if (error)
    return <ErrorState message={error.message} onRetry={() => refetch()} />;
  if (!driver) return <ErrorState message="Driver not found" />;

  const latest = versions[0];
  const selected =
    versions.find((v) => v.id === versionParam) ?? latest ?? null;
  if (!selected) return <ErrorState message="This driver has no versions" />;

  const isLatest = selected.id === latest?.id;
  const colliding = collidingVersions(versions);

  const goToVersion = (versionId: string) =>
    navigate({
      to: "/drivers/$driverId",
      params: { driverId },
      search: { version: versionId },
    });

  return (
    <PageLayout
      title={driver.name}
      breadcrumbs={[
        { label: "Drivers", href: "/drivers" },
        {
          label: `${driver.name} ${displayDriverVersion(selected, colliding)}`,
        },
      ]}
    >
      <div
        data-testid="driver-detail"
        data-driver-id={driver.id}
        data-driver-name={driver.name}
        data-version-id={selected.id}
        data-version-label={selected.version}
        className="max-w-4xl"
      >
        {/* Header: version identity + status on one row. */}
        <div className="flex flex-wrap items-center gap-3 pb-5">
          <div className="flex items-center gap-3">
            <span className="text-sm text-muted-foreground">Version</span>
            {versions.length > 1 ? (
              <Select value={selected.id} onValueChange={goToVersion}>
                <SelectTrigger
                  aria-label="Switch version"
                  className="h-8 w-auto gap-2 px-2.5 font-mono text-base font-medium"
                >
                  {displayDriverVersion(selected, colliding)}
                </SelectTrigger>
                <SelectContent>
                  {versions.map((v) => (
                    <SelectItem key={v.id} value={v.id}>
                      <span className="flex items-center gap-2.5">
                        <span className="font-mono">
                          {displayDriverVersion(v, colliding)}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {formatRelativeTime(v.createdOn)}
                        </span>
                        {v.id === latest?.id && (
                          <Badge variant="success">Latest</Badge>
                        )}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            ) : (
              <span className="font-mono text-base font-medium">
                {displayDriverVersion(selected, colliding)}
              </span>
            )}
            {isLatest && <LatestBadge />}
          </div>

          {/* Older-only notice, kept on the same row (badge + explanation as
              one unit) so it clearly belongs to the selected version.

              NOTE (v1): the copy is intentionally generic — it states the
              latest-wins rule only, with no per-version detail. We deliberately
              do NOT say whether/where this version is in use, because the
              backend does not expose that (`usedBy` / deployment references on
              ApplicationDriverVersion were dropped from v1), and computing it
              purely on the frontend (fetching every deployment and matching
              driverVersionId) is not an efficient or clean path. A backend
              follow-up should add deployment references so we can show
              "used by N deployments" with links and make this message specific.
              See the drivers-v1 scope note. */}
          {!isLatest && (
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2.5 gap-y-1 rounded-lg border border-border bg-muted/40 px-3.5 py-2">
              <OlderBadge />
              <span className="text-[13px] text-muted-foreground">
                New deployments and upgrades use the{" "}
                <Tooltip content={LOADED_SCOPE_NOTE}>
                  <span className="cursor-help underline decoration-dotted underline-offset-2">
                    newest loaded version
                  </span>
                </Tooltip>
                .
              </span>
            </div>
          )}
        </div>

        <Tabs
          tabs={[
            { id: "overview", label: "Overview" },
            {
              id: "parameters",
              label: "Parameters",
              badge: String(selected.parameters.length),
            },
            {
              id: "components",
              label: "Components",
              badge: String(componentCount(selected.components)),
            },
          ]}
          activeTab={activeTab}
          onTabChange={(id) => setActiveTab(id as DetailTab)}
        />

        <div className="pt-5">
          <TabPanel active={activeTab === "overview"}>
            <OverviewPanel version={selected} />
          </TabPanel>
          <TabPanel active={activeTab === "parameters"}>
            <ParametersTab version={selected} />
          </TabPanel>
          <TabPanel active={activeTab === "components"}>
            <ComponentsTab components={selected.components} />
          </TabPanel>
        </div>
      </div>
    </PageLayout>
  );
}

function componentCount(components: DriverVersionDetail["components"]): number {
  if (!isPlainObject(components)) return 0;
  return Object.values(components).filter((v) => isPlainObject(v)).length;
}

function OverviewPanel({ version }: { version: DriverVersionDetail }) {
  const isLocal = version.sourceType === "local";
  const fingerprint = isLocal ? version.contentHash : version.sourceCommitSha;
  const source = isLocal
    ? (version.sourcePath ?? "local")
    : version.sourceBranch
      ? `${version.sourceRepository} @ ${version.sourceBranch}`
      : version.sourceRepository;

  const rows: Array<{ label: string; value: React.ReactNode; copy?: string }> =
    [
      {
        label: "Supports app versions",
        value: mono(version.supportedVersions || "—"),
      },
      { label: isLocal ? "Path" : "Source", value: mono(source), copy: source },
      {
        label: isLocal ? "Content hash" : "Commit",
        value: fingerprint ? mono(fingerprint.slice(0, 12)) : "—",
        copy: fingerprint ?? undefined,
      },
    ];
  if (version.helmChart) {
    rows.push({
      label: "Helm chart",
      value: mono(
        `${version.helmChart.name}${version.helmChart.version ? ` ${version.helmChart.version}` : ""}`,
      ),
    });
    if (version.helmChart.repository) {
      rows.push({
        label: "Chart repository",
        value: mono(version.helmChart.repository),
        copy: version.helmChart.repository,
      });
    }
  }
  rows.push({ label: "Loaded", value: formatRelativeTime(version.createdOn) });

  return (
    <div
      className="overflow-hidden rounded-lg border border-border"
      data-testid="driver-overview"
    >
      <table className="w-full text-sm">
        <tbody>
          {rows.map((row, i) => (
            <tr
              key={row.label}
              className={i < rows.length - 1 ? "border-b border-border/60" : ""}
            >
              <td className="w-52 border-r border-border/60 bg-muted/30 px-4 py-2.5 align-top text-muted-foreground">
                {row.label}
              </td>
              <td className="px-4 py-2.5">
                <span className="inline-flex items-center gap-2">
                  {row.value}
                  {row.copy && <CopyButton text={row.copy} />}
                </span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CopyButton({ text }: { text: string }) {
  const { copied, copy } = useCopyToClipboard();
  return (
    <button
      type="button"
      onClick={() => copy(text)}
      aria-label="Copy to clipboard"
      className="text-muted-foreground transition-colors hover:text-foreground"
    >
      {copied ? (
        <Check className="h-3.5 w-3.5 text-success" />
      ) : (
        <Copy className="h-3.5 w-3.5" />
      )}
    </button>
  );
}

function mono(text: string): React.ReactNode {
  return <span className="font-mono text-[13px]">{text}</span>;
}
