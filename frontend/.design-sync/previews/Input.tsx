import { Input } from 'frontend';

export const Placeholder = () => <Input placeholder="you@example.com" />;
export const Filled = () => <Input defaultValue="jan@opsmill.com" />;
export const Password = () => <Input type="password" defaultValue="hunter2" />;
export const Disabled = () => <Input placeholder="Cluster name" disabled />;
