import * as React from "react";
import { Tooltip as TooltipPrimitive } from "@base-ui/react/tooltip";

import { cn } from "@/lib/utils";

interface TooltipProps {
  content: React.ReactNode;
  children: React.ReactElement;
  /** Hover-open delay in ms. Short by default so it feels responsive. */
  delay?: number;
  className?: string;
}

/**
 * Minimal tooltip wrapper over Base UI. Unlike the native `title` attribute,
 * the open delay is controllable (short by default) so hints appear promptly.
 */
export function Tooltip({
  content,
  children,
  delay = 150,
  className,
}: TooltipProps) {
  return (
    <TooltipPrimitive.Root delay={delay}>
      <TooltipPrimitive.Trigger render={children} />
      <TooltipPrimitive.Portal>
        <TooltipPrimitive.Positioner sideOffset={6} className="z-50">
          <TooltipPrimitive.Popup
            className={cn(
              "max-w-xs rounded-md border border-border bg-popover px-2.5 py-1.5 text-xs leading-relaxed text-popover-foreground shadow-md",
              "data-[open]:animate-in data-[closed]:animate-out data-[closed]:fade-out-0 data-[open]:fade-in-0",
              className,
            )}
          >
            {content}
          </TooltipPrimitive.Popup>
        </TooltipPrimitive.Positioner>
      </TooltipPrimitive.Portal>
    </TooltipPrimitive.Root>
  );
}
