import * as React from "react";
import { Collapsible as CollapsiblePrimitive } from "@base-ui/react/collapsible";

const Collapsible = CollapsiblePrimitive.Root;

const CollapsibleTrigger = React.forwardRef<
  HTMLButtonElement,
  React.ComponentPropsWithoutRef<typeof CollapsiblePrimitive.Trigger> & {
    asChild?: boolean;
  }
>(({ asChild, children, ...props }, ref) => {
  if (asChild) {
    if (import.meta.env.DEV && !React.isValidElement(children)) {
      console.error(
        "[CollapsibleTrigger] asChild requires a single React element child.",
      );
    }
    if (React.isValidElement(children)) {
      return (
        <CollapsiblePrimitive.Trigger
          ref={ref}
          render={children as React.ReactElement<Record<string, unknown>>}
          {...props}
        />
      );
    }
  }
  return (
    <CollapsiblePrimitive.Trigger ref={ref} {...props}>
      {children}
    </CollapsiblePrimitive.Trigger>
  );
});
CollapsibleTrigger.displayName = "CollapsibleTrigger";

const CollapsibleContent = CollapsiblePrimitive.Panel;

export { Collapsible, CollapsibleTrigger, CollapsibleContent };
