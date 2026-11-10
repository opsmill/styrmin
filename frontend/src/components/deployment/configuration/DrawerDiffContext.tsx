import { createContext, useContext, useMemo, type ReactNode } from "react";
import { useStore } from "@tanstack/react-form";

import type { UpdateDeploymentInput } from "@/generated/graphql";
import { diff } from "@/lib/config-diff";
import type {
  ConfigurationDiff,
  DriverParameterSchema,
} from "@/lib/configuration-types";
import { validateImageReference } from "@/lib/image-reference";
import { servicesWithInvalidSuffix } from "@/lib/fqdn-suffix";
import { servicesWithInvalidClass } from "@/lib/ingress-class";
import { replicaFieldError } from "@/lib/replicas";

/** Components whose override fails validation, per field. */
export interface DrawerInvalidFields {
  images: readonly string[];
  replicas: readonly string[];
  /** Services whose ingress override has an FQDN suffix that is not a DNS name (#598). */
  services: readonly string[];
  /** Services whose ingress override has an ingress class that is not a Kubernetes object name (#598). */
  serviceClasses: readonly string[];
}

const NO_INVALID_FIELDS: DrawerInvalidFields = {
  images: [],
  replicas: [],
  services: [],
  serviceClasses: [],
};

const DrawerDiffContextValue = createContext<ConfigurationDiff | null>(null);
const DrawerInvalidFieldsValue =
  createContext<DrawerInvalidFields>(NO_INVALID_FIELDS);

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
 * `diff()` on every keystroke. The diff function is linear in the number
 * of fields (asserted in `config-diff.test.ts`) but the worst case —
 * 50 components × 50 fields — is a lot of fields, and running it 8× per
 * keystroke compounded that 8× live. A single shared subscription +
 * memoised diff fixes that.
 *
 * Consumers that need a per-section count filter the shared `entries`
 * array; that filter is O(entries) — cheap relative to a re-run of
 * `diff`.
 *
 * Also exposes the components whose image override or replica count fails
 * validation, derived from the values so the footer can block Review & apply
 * and name them.
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

  const invalidFields = useMemo<DrawerInvalidFields>(() => {
    const blocks = (currentValues.components ?? []).filter(Boolean);
    return {
      images: blocks
        .filter((block) => block.image && validateImageReference(block.image))
        .map((block) => block.name),
      replicas: blocks
        .filter((block) => replicaFieldError(block.replicas))
        .map((block) => block.name),
      services: servicesWithInvalidSuffix(currentValues.services),
      serviceClasses: servicesWithInvalidClass(currentValues.services),
    };
  }, [currentValues.components, currentValues.services]);

  return (
    <DrawerDiffContextValue.Provider value={diffResult}>
      <DrawerInvalidFieldsValue.Provider value={invalidFields}>
        {children}
      </DrawerInvalidFieldsValue.Provider>
    </DrawerDiffContextValue.Provider>
  );
}

/** Components with an invalid image or replica count; Review & apply stays blocked while any remain. */
export function useDrawerInvalidFields(): DrawerInvalidFields {
  return useContext(DrawerInvalidFieldsValue);
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
