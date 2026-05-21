import { Tabs, TabPanel } from "@/components/ui/tabs";
import { VersionHeader } from "./VersionHeader";
import { OverviewTab } from "./tabs/OverviewTab";
import { ParametersTab } from "./tabs/ParametersTab";
import { ComponentsTab } from "./tabs/ComponentsTab";
import { ActionsTab } from "./tabs/ActionsTab";
import type { DriverVersionDetail, TabId } from "./types";

interface VersionDetailProps {
  version: DriverVersionDetail;
  activeTab: TabId;
  onTabChange: (tab: TabId) => void;
}

const TABS: ReadonlyArray<{ id: TabId; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "parameters", label: "Parameters" },
  { id: "components", label: "Components" },
  { id: "actions", label: "Actions" },
  { id: "source", label: "Source" },
];

/**
 * Right-pane scaffold for the selected driver version. Wires the version
 * header, the five-tab strip (all five from day one, per the spec), and the
 * matching tab panels.
 *
 * Only the Source panel still renders a placeholder; it will gain content in
 * a later chunk (US3).
 */
export function VersionDetail({
  version,
  activeTab,
  onTabChange,
}: VersionDetailProps) {
  return (
    <div
      className="flex min-w-0 flex-1 flex-col gap-6"
      data-testid="driver-version-detail"
      data-version-id={version.id}
    >
      <VersionHeader version={version} />
      <Tabs
        tabs={TABS.map((tab) => ({ id: tab.id, label: tab.label }))}
        activeTab={activeTab}
        onTabChange={(id) => onTabChange(id as TabId)}
      />
      <TabPanel active={activeTab === "overview"}>
        <OverviewTab version={version} />
      </TabPanel>
      <TabPanel active={activeTab === "parameters"}>
        <ParametersTab version={version} />
      </TabPanel>
      <TabPanel active={activeTab === "components"}>
        <ComponentsTab components={version.components} />
      </TabPanel>
      <TabPanel active={activeTab === "actions"}>
        <ActionsTab actions={version.actions} />
      </TabPanel>
      <TabPanel active={activeTab === "source"}>
        <PlaceholderPanel label="Source" />
      </TabPanel>
    </div>
  );
}

function PlaceholderPanel({ label }: { label: string }) {
  return (
    <p
      className="text-sm italic text-muted-foreground"
      data-testid="driver-tab-placeholder"
    >
      {label} content coming in a later chunk
    </p>
  );
}
