import { createContext, useContext, useMemo, type ReactNode } from "react";
import { useStore } from "@tanstack/react-form";

import type { UpdateDeploymentInput } from "@/generated/graphql";
import { diff } from "@/lib/config-diff";
import type {
  ConfigurationDiff,
  DriverParameterSchema,
} from "@/lib/configuration-types";

const DrawerDiffContextValue = createContext<ConfigurationDiff | null>(null);

interface FormLike {
  store: Parameters<typeof useStore>[0];
}

interface ProviderProps {
  form: FormLike;
  initialValues: UpdateDeploymentInput;
  driverSchema: DriverParameterSchema;
  children: ReactNode;
}

/**
 * Subscribes once to the drawer's form store, runs the canonical
 * {@link diff} helper against the captured {@link initialValues}, and
 * exposes the result to every drawer descendant.
 *
 * Why: previously SectionNav, DrawerFooter, ConfigDiffDialog, and every
 * edit section each subscribed to the form store and ran their own
 * `diff()` on every keystroke. The diff function is O(fields) and the
 * worst-case bound (50 components × 50 fields) sits just under the
 * 5 ms perf budget — running it 8× per keystroke compounded the cost
 * 8× live. A single shared subscription + memoised diff fixes that.
 *
 * Consumers that need a per-section count filter the shared `entries`
 * array; that filter is O(entries) — cheap relative to a re-run of
 * `diff`.
 */
export function DrawerDiffProvider({
  form,
  initialValues,
  driverSchema,
  children,
}: ProviderProps) {
  const currentValues = useStore(
    form.store,
    (s) => (s as { values: UpdateDeploymentInput }).values,
  );

  const diffResult = useMemo(
    () => diff(initialValues, currentValues, driverSchema),
    [initialValues, currentValues, driverSchema],
  );

  return (
    <DrawerDiffContextValue.Provider value={diffResult}>
      {children}
    </DrawerDiffContextValue.Provider>
  );
}

export function useDrawerDiff(): ConfigurationDiff {
  const value = useContext(DrawerDiffContextValue);
  if (value === null) {
    throw new Error(
      "useDrawerDiff must be used inside <DrawerDiffProvider>. " +
        "If this error fires in a test, wrap the component in <DrawerDiffProvider> " +
        "or render via <ConfigEditDrawer>.",
    );
  }
  return value;
}
