import { Checkbox, Label } from 'frontend';

const Row = ({ children }) => (
  <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>{children}</div>
);

export const Unchecked = () => (
  <Row><Checkbox id="c1" /><Label htmlFor="c1">Unchecked</Label></Row>
);
export const Checked = () => (
  <Row><Checkbox id="c2" defaultChecked /><Label htmlFor="c2">Checked</Label></Row>
);
export const Disabled = () => (
  <Row><Checkbox id="c3" disabled /><Label htmlFor="c3">Disabled</Label></Row>
);
export const DisabledChecked = () => (
  <Row><Checkbox id="c4" defaultChecked disabled /><Label htmlFor="c4">Disabled + checked</Label></Row>
);
export const WithLabel = () => (
  <Row><Checkbox id="c5" defaultChecked /><Label htmlFor="c5">Enable automatic upgrades</Label></Row>
);
