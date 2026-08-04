import { Tabs, TabPanel } from 'frontend';

const tabs = [
  { id: 'overview', label: 'Overview' },
  { id: 'pods', label: 'Pods', badge: '12' },
  { id: 'events', label: 'Events' },
  { id: 'logs', label: 'Logs' },
];

export const Default = () => (
  <div className="w-[480px]">
    <Tabs tabs={tabs} activeTab="pods" onTabChange={() => {}} />
    <TabPanel active>
      <div className="p-4 text-sm text-muted-foreground">
        12 pods running across 3 components.
      </div>
    </TabPanel>
  </div>
);
