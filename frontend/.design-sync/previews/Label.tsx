import { Label, Input } from 'frontend';

export const Default = () => <Label htmlFor="email">Email address</Label>;

export const WithInput = () => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxWidth: 260 }}>
    <Label htmlFor="cluster">Cluster name</Label>
    <Input id="cluster" placeholder="production-eu" />
  </div>
);

export const Required = () => (
  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, maxWidth: 260 }}>
    <Label htmlFor="namespace">Namespace *</Label>
    <Input id="namespace" defaultValue="styrmin-system" />
  </div>
);
