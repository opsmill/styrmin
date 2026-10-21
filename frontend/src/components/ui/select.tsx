import * as React from "react";
import { Select as SelectPrimitive } from "@base-ui/react/select";
import { Check, ChevronDown, ChevronUp } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Pass `items`, a list of `{ value, label }`, whenever an item's label differs
 * from its value: without it, `<SelectValue>` shows the raw value, for example
 * an id, in the trigger.
 */
function Select({
  value,
  onValueChange,
  ...props
}: Omit<
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Root>,
  "onValueChange"
> & {
  onValueChange?: (value: string) => void;
}) {
  // Base UI's Select uses ``alignItemWithTrigger: true`` by default and looks
  // up the item matching ``value`` to anchor the popup. Passing ``""`` when
  // nothing is selected (TanStack Form's string default) doesn't match any
  // ``<SelectItem>`` and sends positioning into a fallback that renders the
  // popup full-height at a clipped location — visually it looks like the
  // dropdown never opens. Base UI treats ``null`` explicitly as "no value",
  // so map empty-string → null on the way in.
  const normalisedValue = value === "" ? null : value;
  return (
    <SelectPrimitive.Root
      value={normalisedValue}
      onValueChange={
        onValueChange
          ? (nextValue: unknown) => {
              if (typeof nextValue === "string") {
                onValueChange(nextValue);
              } else if (nextValue === null) {
                // User cleared the selection — surface as empty string so
                // controlled callers keep receiving strings.
                onValueChange("");
              } else if (import.meta.env.DEV) {
                console.warn(
                  "[Select] onValueChange received a non-string value:",
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
const SelectGroup = SelectPrimitive.Group;
const SelectValue = SelectPrimitive.Value;

const SelectTrigger = React.forwardRef<
  HTMLButtonElement,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>
>(({ className, children, ...props }, ref) => (
  <SelectPrimitive.Trigger
    ref={ref}
    className={cn(
      "flex h-9 w-full items-center justify-between whitespace-nowrap rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm ring-offset-background placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50 [&>span]:line-clamp-1",
      className,
    )}
    {...props}
  >
    {children}
    <SelectPrimitive.Icon
      render={<ChevronDown className="h-4 w-4 opacity-50" />}
    />
  </SelectPrimitive.Trigger>
));
SelectTrigger.displayName = "SelectTrigger";

const SelectScrollUpButton = React.forwardRef<
  HTMLDivElement,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollUpArrow>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.ScrollUpArrow
    ref={ref}
    className={cn(
      "flex cursor-default items-center justify-center py-1",
      className,
    )}
    {...props}
  >
    <ChevronUp className="h-4 w-4" />
  </SelectPrimitive.ScrollUpArrow>
));
SelectScrollUpButton.displayName = "SelectScrollUpButton";

const SelectScrollDownButton = React.forwardRef<
  HTMLDivElement,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.ScrollDownArrow>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.ScrollDownArrow
    ref={ref}
    className={cn(
      "flex cursor-default items-center justify-center py-1",
      className,
    )}
    {...props}
  >
    <ChevronDown className="h-4 w-4" />
  </SelectPrimitive.ScrollDownArrow>
));
SelectScrollDownButton.displayName = "SelectScrollDownButton";

const SelectContent = React.forwardRef<
  HTMLDivElement,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Popup> & {
    position?: string;
  }
>(({ className, children, position = "popper", ...props }, ref) => (
  // ``alignItemWithTrigger`` defaults to ``true``, which stacks the popup
  // directly over the trigger so the selected item lines up with it. With no
  // selected value the popup still centres on the trigger rect, making the
  // trigger button eat every pointer event aimed at an option underneath.
  // Disable it so the popup anchors below (or flipped above) the trigger —
  // the usual dropdown behaviour everywhere else in the app expects.
  //
  // Both the ``Dialog`` and ``Select`` popups share the same Base UI portal
  // (``FloatingPortal`` contextually defaults to the nearest ancestor portal
  // inside a Dialog). The Popup child is ``z-50`` but its parent Positioner
  // is absolute-positioned with ``z-index: auto``, so at the portal root the
  // positioner sits at the z-auto level while the Dialog popup sits at z-50.
  // The Select popup's z-50 only promotes it within the Positioner's own
  // stacking context — the whole subtree still paints below any z-50 Dialog.
  // Promote the Positioner to z-50 so the Select popup and the Dialog popup
  // are siblings at the same level and DOM order decides (Select is later).
  <SelectPrimitive.Portal>
    <SelectPrimitive.Positioner
      alignItemWithTrigger={false}
      sideOffset={4}
      className="z-50"
    >
      <SelectPrimitive.Popup
        ref={ref}
        className={cn(
          "relative z-50 max-h-96 min-w-[8rem] overflow-hidden rounded-md border bg-popover text-popover-foreground shadow-md data-[open]:animate-in data-[closed]:animate-out data-[closed]:fade-out-0 data-[open]:fade-in-0 data-[closed]:zoom-out-95 data-[open]:zoom-in-95 data-[side=bottom]:slide-in-from-top-2 data-[side=left]:slide-in-from-right-2 data-[side=right]:slide-in-from-left-2 data-[side=top]:slide-in-from-bottom-2",
          position === "popper" &&
            "data-[side=bottom]:translate-y-1 data-[side=left]:-translate-x-1 data-[side=right]:translate-x-1 data-[side=top]:-translate-y-1",
          className,
        )}
        {...props}
      >
        <SelectScrollUpButton />
        <SelectPrimitive.List
          className={cn(
            "p-1",
            position === "popper" && "w-full min-w-[var(--anchor-width)]",
          )}
        >
          {children}
        </SelectPrimitive.List>
        <SelectScrollDownButton />
      </SelectPrimitive.Popup>
    </SelectPrimitive.Positioner>
  </SelectPrimitive.Portal>
));
SelectContent.displayName = "SelectContent";

const SelectLabel = React.forwardRef<
  HTMLDivElement,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.GroupLabel>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.GroupLabel
    ref={ref}
    className={cn("px-2 py-1.5 text-sm font-semibold", className)}
    {...props}
  />
));
SelectLabel.displayName = "SelectLabel";

const SelectItem = React.forwardRef<
  HTMLDivElement,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item>
>(({ className, children, value, ...props }, ref) => (
  // Base UI's ``Select.Item`` keeps ``value`` in internal state rather than
  // on the DOM. Mirror it to ``data-value`` so tests (and any caller that
  // needs a stable selector) can target an option by its value without
  // scraping text content.
  <SelectPrimitive.Item
    ref={ref}
    value={value}
    data-value={typeof value === "string" ? value : undefined}
    className={cn(
      "relative flex w-full cursor-default select-none items-center rounded-sm py-1.5 pl-2 pr-8 text-sm outline-none focus:bg-accent focus:text-accent-foreground data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
      className,
    )}
    {...props}
  >
    <span className="absolute right-2 flex h-3.5 w-3.5 items-center justify-center">
      <SelectPrimitive.ItemIndicator>
        <Check className="h-4 w-4" />
      </SelectPrimitive.ItemIndicator>
    </span>
    <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
  </SelectPrimitive.Item>
));
SelectItem.displayName = "SelectItem";

const SelectSeparator = React.forwardRef<
  HTMLDivElement,
  React.ComponentPropsWithoutRef<typeof SelectPrimitive.Separator>
>(({ className, ...props }, ref) => (
  <SelectPrimitive.Separator
    ref={ref}
    className={cn("-mx-1 my-1 h-px bg-muted", className)}
    {...props}
  />
));
SelectSeparator.displayName = "SelectSeparator";

export {
  Select,
  SelectGroup,
  SelectValue,
  SelectTrigger,
  SelectContent,
  SelectLabel,
  SelectItem,
  SelectSeparator,
  SelectScrollUpButton,
  SelectScrollDownButton,
};
