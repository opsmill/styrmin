import * as React from "react";
import { Combobox as ComboboxPrimitive } from "@base-ui/react/combobox";
import { Check, ChevronDown, Search } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Combobox — a `Select` whose popup carries a search field.
 *
 * Pass the full option list as `items` and render rows through
 * `ComboboxList`'s function child, which receives only the matches.
 * `ComboboxItem` takes the plain string value.
 */

export interface ComboboxOption {
  /** Value used by `ComboboxItem` and the Root's `value`. */
  value: string;
  /** What the search field matches against. */
  label: string;
}

function Combobox<T extends ComboboxOption>({
  value,
  onValueChange,
  ...props
}: Omit<
  React.ComponentPropsWithoutRef<typeof ComboboxPrimitive.Root>,
  "value" | "onValueChange" | "items"
> & {
  value?: string | null;
  onValueChange?: (value: string) => void;
  items: readonly T[];
}) {
  // Base UI treats `null` as "no value"; `""` matches no item and renders the
  // popup clipped. Same normalisation as select.tsx.
  const normalisedValue = value === "" ? null : value;
  return (
    <ComboboxPrimitive.Root
      value={normalisedValue}
      onValueChange={
        onValueChange
          ? (nextValue: unknown) => {
              if (typeof nextValue === "string") {
                onValueChange(nextValue);
              } else if (nextValue === null) {
                onValueChange("");
              } else if (import.meta.env.DEV) {
                console.warn(
                  "[Combobox] onValueChange received a non-string value:",
                  nextValue,
                );
              }
            }
          : undefined
      }
      {...props}
    />
  );
}

const ComboboxTrigger = React.forwardRef<
  HTMLButtonElement,
  React.ComponentPropsWithoutRef<typeof ComboboxPrimitive.Trigger>
>(({ className, children, ...props }, ref) => (
  <ComboboxPrimitive.Trigger
    ref={ref}
    className={cn(
      "flex h-9 w-full items-center justify-between whitespace-nowrap rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm ring-offset-background focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
      className,
    )}
    {...props}
  >
    {children}
    <ComboboxPrimitive.Icon
      render={<ChevronDown className="h-4 w-4 opacity-50" />}
    />
  </ComboboxPrimitive.Trigger>
));
ComboboxTrigger.displayName = "ComboboxTrigger";

const ComboboxContent = React.forwardRef<
  HTMLDivElement,
  React.ComponentPropsWithoutRef<typeof ComboboxPrimitive.Popup>
>(({ className, children, ...props }, ref) => (
  // Portal > Positioner > Popup per ui-primitives.md. Positioning props and
  // the z-index belong on the Positioner, else the popup sits below a Dialog.
  <ComboboxPrimitive.Portal>
    <ComboboxPrimitive.Positioner align="start" sideOffset={4} className="z-50">
      <ComboboxPrimitive.Popup
        ref={ref}
        className={cn(
          "relative z-50 min-w-[var(--anchor-width)] overflow-hidden rounded-md border bg-popover text-popover-foreground shadow-md data-[open]:animate-in data-[closed]:animate-out data-[closed]:fade-out-0 data-[open]:fade-in-0 data-[closed]:zoom-out-95 data-[open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=top]:slide-in-from-bottom-2",
          className,
        )}
        {...props}
      >
        {children}
      </ComboboxPrimitive.Popup>
    </ComboboxPrimitive.Positioner>
  </ComboboxPrimitive.Portal>
));
ComboboxContent.displayName = "ComboboxContent";

/** Search field. Renders inside `ComboboxContent`, above the list. */
const ComboboxSearch = React.forwardRef<
  HTMLInputElement,
  React.ComponentPropsWithoutRef<typeof ComboboxPrimitive.Input>
>(({ className, ...props }, ref) => (
  <div className="relative p-2">
    <Search className="pointer-events-none absolute left-4.5 top-1/2 z-10 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
    <ComboboxPrimitive.Input
      ref={ref}
      className={cn(
        "flex h-9 w-full rounded-md border border-input bg-transparent pl-8 pr-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring",
        className,
      )}
      {...props}
    />
  </div>
));
ComboboxSearch.displayName = "ComboboxSearch";

const ComboboxList = React.forwardRef<
  HTMLDivElement,
  React.ComponentPropsWithoutRef<typeof ComboboxPrimitive.List>
>(({ className, ...props }, ref) => (
  <ComboboxPrimitive.List
    ref={ref}
    className={cn("max-h-64 overflow-auto border-t p-1", className)}
    {...props}
  />
));
ComboboxList.displayName = "ComboboxList";

const ComboboxItem = React.forwardRef<
  HTMLDivElement,
  React.ComponentPropsWithoutRef<typeof ComboboxPrimitive.Item>
>(({ className, children, value, ...props }, ref) => (
  // Base UI keeps `value` in internal state; mirror it for test selectors.
  <ComboboxPrimitive.Item
    ref={ref}
    value={value}
    data-value={typeof value === "string" ? value : undefined}
    className={cn(
      "relative flex w-full cursor-default select-none items-center rounded-sm py-1.5 pl-2 pr-8 text-sm outline-none data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground data-[selected]:bg-accent/60",
      className,
    )}
    {...props}
  >
    <span className="absolute right-2 flex h-3.5 w-3.5 items-center justify-center">
      <ComboboxPrimitive.ItemIndicator>
        <Check className="h-4 w-4" />
      </ComboboxPrimitive.ItemIndicator>
    </span>
    {children}
  </ComboboxPrimitive.Item>
));
ComboboxItem.displayName = "ComboboxItem";

/** Shown in place of the list when the search matches nothing. */
const ComboboxEmpty = React.forwardRef<
  HTMLDivElement,
  React.ComponentPropsWithoutRef<typeof ComboboxPrimitive.Empty>
>(({ className, ...props }, ref) => (
  <ComboboxPrimitive.Empty
    ref={ref}
    className={cn(
      "border-t px-3 py-2.5 text-sm text-muted-foreground",
      className,
    )}
    {...props}
  />
));
ComboboxEmpty.displayName = "ComboboxEmpty";

/** Strip under the list, for counts and scope notes. */
const ComboboxFooter = React.forwardRef<
  HTMLDivElement,
  React.HTMLAttributes<HTMLDivElement>
>(({ className, ...props }, ref) => (
  <div
    ref={ref}
    className={cn(
      "border-t px-3 py-1.5 text-xs text-muted-foreground",
      className,
    )}
    {...props}
  />
));
ComboboxFooter.displayName = "ComboboxFooter";

export {
  Combobox,
  ComboboxTrigger,
  ComboboxContent,
  ComboboxSearch,
  ComboboxList,
  ComboboxItem,
  ComboboxEmpty,
  ComboboxFooter,
};
