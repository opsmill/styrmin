import { useMemo, useState } from "react";
import { useNavigate, useParams, useSearch } from "@tanstack/react-router";
import { Copy, Check, ExternalLink } from "lucide-react";
import { useGetDriverQuery } from "@/generated/graphql";
import { PageLayout } from "@/components/PageLayout";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabPanel } from "@/components/ui/tabs";
import {
  Combobox,
  ComboboxTrigger,
  ComboboxContent,
  ComboboxSearch,
  ComboboxList,
  ComboboxItem,
  ComboboxEmpty,
  ComboboxFooter,
} from "@/components/ui/combobox";
import { LatestBadge, OlderBadge } from "./VersionStatusBadge";
import { DriverLogo } from "./DriverLogo";
import { ClampedText } from "@/components/ClampedText";
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
  const [versionQuery, setVersionQuery] = useState("");

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

  // `label` is what the search matches on, so it carries the displayed string
  // including the `@<short>` suffix added when two versions collide.
  const versionOptions = versions.map((v) => ({
    value: v.id,
    label: displayDriverVersion(v, colliding),
    loaded: formatRelativeTime(v.createdOn),
  }));

  const goToVersion = (versionId: string) =>
    navigate({
      to: "/drivers/$driverId",
      params: { driverId },
      search: { version: versionId },
    });

  return (
    <PageLayout
      title={driver.name}
      icon={<DriverLogo icon={selected.icon} size="md" loading="eager" />}
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
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 pb-5">
          <div className="flex items-center gap-3">
            <span className="text-sm text-muted-foreground">Version</span>
            {versions.length > 1 ? (
              <Combobox
                items={versionOptions}
                value={selected.id}
                onValueChange={goToVersion}
                inputValue={versionQuery}
                onInputValueChange={setVersionQuery}
              >
                <ComboboxTrigger
                  aria-label="Switch version"
                  className="h-8 w-auto gap-2 px-2.5 font-mono text-base font-medium"
                >
                  {displayDriverVersion(selected, colliding)}
                </ComboboxTrigger>
                <ComboboxContent className="w-72">
                  <ComboboxSearch
                    placeholder={`Search ${versions.length} versions…`}
                    aria-label="Search versions"
                  />
                  <ComboboxList>
                    {(option: (typeof versionOptions)[number]) => (
                      <ComboboxItem key={option.value} value={option.value}>
                        <span className="flex w-full items-center gap-2.5">
                          <span className="font-mono font-medium">
                            {option.label}
                          </span>
                          {option.value === latest?.id && (
                            <Badge variant="success">Latest</Badge>
                          )}
                          <span className="ml-auto text-xs text-muted-foreground">
                            {option.loaded}
                          </span>
                        </span>
                      </ComboboxItem>
                    )}
                  </ComboboxList>
                  <ComboboxEmpty>
                    No version matches "{versionQuery.trim()}"
                  </ComboboxEmpty>
                  <ComboboxFooter>
                    {versionQuery.trim()
                      ? `Searching all ${versions.length} loaded versions`
                      : `Newest first · type to search all ${versions.length} versions`}
                  </ComboboxFooter>
                </ComboboxContent>
              </Combobox>
            ) : (
              <span className="font-mono text-base font-medium">
                {displayDriverVersion(selected, colliding)}
              </span>
            )}
            {isLatest && <LatestBadge />}
          </div>

          {/* Older-only notice: the badge and its explanation are a single
              claim, so they share one bordered, tinted surface — the sentence
              reads as the badge's caption rather than as a stray line under
              the row. The badge still occupies the same slot as "Latest",
              directly after the picker.

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
            <div className="flex min-w-0 flex-wrap items-center gap-x-2.5 gap-y-1 rounded-lg border border-warning/40 bg-warning/10 py-1.5 pl-1.5 pr-3">
              <OlderBadge />
              {/* Full foreground, not muted: muted-foreground at 13px over the
                  tinted surface measures 3.95:1, under the 4.5:1 AA floor.
                  The DS's own Alert uses foreground on a notice surface. */}
              <span className="text-[13px] text-foreground">
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

          {versions.length > 1 && (
            <span className="text-[13px] text-muted-foreground">
              {versions.length} driver versions loaded
            </span>
          )}
        </div>

        {selected.description && (
          <div className="pb-5">
            <ClampedText
              key={selected.id}
              lines={3}
              data-testid="driver-description"
              className="whitespace-pre-line text-sm text-muted-foreground"
            >
              {selected.description}
            </ClampedText>
          </div>
        )}

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
            <ComponentsTab
              components={selected.components}
              componentConfigs={selected.componentConfigs}
            />
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
    <div className="space-y-5" data-testid="driver-overview">
      <div className="overflow-hidden rounded-lg border border-border">
        <table className="w-full text-sm">
          <tbody>
            {rows.map((row, i) => (
              <tr
                key={row.label}
                className={
                  i < rows.length - 1 ? "border-b border-border/60" : ""
                }
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

      {version.links.length > 0 && (
        <section className="overflow-hidden rounded-lg border border-border">
          <h2 className="border-b border-border/60 bg-muted/30 px-4 py-2.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Links
          </h2>
          <ul
            data-testid="driver-links"
            className="divide-y divide-border/60 text-sm"
          >
            {version.links.map((link, i) => (
              <li
                key={i}
                className="flex flex-wrap items-baseline gap-x-2 px-4 py-2.5"
              >
                <a
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 font-medium text-primary underline-offset-4 hover:underline"
                >
                  {link.label}
                  <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                  {/* A flex container drops this space from the layout, not from the name. */}{" "}
                  <span className="sr-only">(opens in a new tab)</span>
                </a>
                <span
                  data-testid="driver-link-host"
                  className="text-xs text-muted-foreground"
                >
                  {linkHost(link.url)}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

/** Host the link goes to, such as `docs.example.com`. */
function linkHost(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
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
