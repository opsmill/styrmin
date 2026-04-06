import * as React from "react";

import { cn } from "@/lib/utils";

interface SlotProps extends React.HTMLAttributes<HTMLElement> {
  children?: React.ReactNode;
}

const Slot = React.forwardRef<HTMLElement, SlotProps>(
  ({ children, ...props }, ref) => {
    if (!React.isValidElement<Record<string, unknown>>(children)) {
      if (import.meta.env.DEV) {
        console.error(
          "[Slot] Expected a single React element child, but received:",
          children,
        );
      }
      return null;
    }
    return React.cloneElement(children, {
      ...props,
      ...children.props,
      ref,
      className: cn(
        props.className as string,
        children.props.className as string,
      ),
    });
  },
);
Slot.displayName = "Slot";

export { Slot };
