import { Collapsible, CollapsibleTrigger, CollapsibleContent } from 'frontend';

export const Default = () => (
  <Collapsible defaultOpen className="w-[360px]">
    <CollapsibleTrigger className="font-medium">
      Advanced settings
    </CollapsibleTrigger>
    <CollapsibleContent className="pt-2 text-sm text-muted-foreground">
      Configure reconcile intervals, drift detection, and rollback behavior for this deployment.
    </CollapsibleContent>
  </Collapsible>
);
