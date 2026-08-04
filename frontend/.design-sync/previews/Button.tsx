import { Button } from 'frontend';

export const Default = () => <Button>Button</Button>;
export const Secondary = () => <Button variant="secondary">Secondary</Button>;
export const Destructive = () => <Button variant="destructive">Delete</Button>;
export const Outline = () => <Button variant="outline">Outline</Button>;
export const Ghost = () => <Button variant="ghost">Ghost</Button>;
export const Sizes = () => (
  <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
    <Button size="sm">Small</Button>
    <Button>Default</Button>
    <Button size="lg">Large</Button>
  </div>
);
