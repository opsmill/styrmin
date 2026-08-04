import { Separator } from 'frontend';

export const Horizontal = () => (
  <div style={{ maxWidth: 280 }}>
    <div style={{ fontSize: 14, fontWeight: 500 }}>Deployment settings</div>
    <Separator style={{ margin: '12px 0' }} />
    <div style={{ fontSize: 13, opacity: 0.7 }}>Configure how instances roll out.</div>
  </div>
);

export const Vertical = () => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 12, height: 20, fontSize: 13 }}>
    <span>Clusters</span>
    <Separator orientation="vertical" />
    <span>Environments</span>
    <Separator orientation="vertical" />
    <span>Deployments</span>
  </div>
);
