import { Alert, AlertTitle, AlertDescription } from 'frontend';

export const Default = () => (
  <Alert>
    <AlertTitle>Deployment scheduled</AlertTitle>
    <AlertDescription>
      Your changes will be applied to the production cluster during the next reconcile cycle.
    </AlertDescription>
  </Alert>
);

export const Destructive = () => (
  <Alert variant="destructive">
    <AlertTitle>Reconcile failed</AlertTitle>
    <AlertDescription>
      The driver could not connect to the target cluster. Check the agent status and retry.
    </AlertDescription>
  </Alert>
);
