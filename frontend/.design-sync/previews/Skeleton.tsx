import { Skeleton } from 'frontend';

export const Line = () => <Skeleton style={{ height: 16, width: 220 }} />;

export const Block = () => <Skeleton style={{ height: 96, width: 260 }} />;

export const Avatar = () => <Skeleton style={{ height: 40, width: 40, borderRadius: '9999px' }} />;

export const Card = () => (
  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
    <Skeleton style={{ height: 40, width: 40, borderRadius: '9999px' }} />
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <Skeleton style={{ height: 14, width: 160 }} />
      <Skeleton style={{ height: 12, width: 100 }} />
    </div>
  </div>
);
