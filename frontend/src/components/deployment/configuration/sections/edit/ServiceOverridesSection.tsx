// Section components bind to arbitrary dotted sub-paths under
// `UpdateDeploymentInput`; the TanStack Form per-path generic narrowing is
// not usable across the full schema, so `form.Field` children are typed as
// `any` and validated through the section's Zod schema and runtime guards
// inside each input.
/* eslint-disable @typescript-eslint/no-explicit-any */
import { X } from "lucide-react";
import { z } from "zod";

import type { ReactFormLike } from "./types";

import type {
  ServiceNameOverride,
  UpdateDeploymentInput,
} from "@/generated/graphql";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { SectionId } from "@/lib/configuration-types";

import { ChangedFieldFrame } from "../../ChangedFieldFrame";
import { useDrawerDiff } from "../../DrawerDiffContext";

// RFC 1035 service name regex: starts with letter, ends with alphanumeric,
// up to 63 chars. We keep the simpler form here; the backend re-validates.
const RFC_1035 = /^[a-z]([-a-z0-9]*[a-z0-9])?$/;

/**
 * Zod schema for the `Service Overrides` slice (data-model.md "Service
 * Overrides" row).
 *
 * Rules:
 *  - `driverServiceName` must be a non-empty string. Ideally constrained to
 *    services declared by the driver, but `applicationDriverVersion.services`
 *    is not currently surfaced through the drawer prop chain (the
 *    `driverSchema` prop only carries parameter definitions). We accept any
 *    non-empty string for v1 and let the backend reject unknown service
 *    references with its existing validation; v2 should pipe the driver's
 *    `services: ServiceDefinition[]` list through and switch this to a Select.
 *  - `overrideName` matches the RFC 1035 service-name regex and must be
 *    unique within the list.
 */
export const serviceOverridesSchema = z
  .array(
    z.object({
      driverServiceName: z.string().min(1, "Driver service is required"),
      overrideName: z
        .string()
        .min(1, "Override name is required")
        .max(63, "Override name must be 63 characters or fewer")
        .regex(
          RFC_1035,
          "Must be a valid RFC 1035 service name (lowercase, kebab-case).",
        ),
    }),
  )
  .superRefine((rows: any, ctx: any) => {
    const seenDriver = new Map<string, number>();
    const seenOverride = new Map<string, number>();
    rows.forEach((row: any, index: number) => {
      const previousDriver = seenDriver.get(row.driverServiceName);
      if (previousDriver !== undefined) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: `Driver service "${row.driverServiceName}" already overridden at row ${
            previousDriver + 1
          }.`,
          path: [index, "driverServiceName"],
        });
      } else if (row.driverServiceName) {
        seenDriver.set(row.driverServiceName, index);
      }
      const previousOverride = seenOverride.get(row.overrideName);
      if (previousOverride !== undefined) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          message: `Duplicate override name "${row.overrideName}" (also at row ${
            previousOverride + 1
          }).`,
          path: [index, "overrideName"],
        });
      } else if (row.overrideName) {
        seenOverride.set(row.overrideName, index);
      }
    });
  });

function emptyRow(): ServiceNameOverride {
  return { driverServiceName: "", overrideName: "" };
}

interface Props {
  form: ReactFormLike;
  initial: UpdateDeploymentInput;
  environment: UpdateDeploymentInput;
  /**
   * Driver-declared service names available for override. Sourced from
   * `deployment.deployedServices[].driverServiceName` so we constrain the
   * "which driver service to rename" picker to only valid choices.
   *
   * Optional for backwards compat with sites that have not yet threaded
   * the list through; when omitted, the picker falls back to a free-text
   * input.
   */
  driverServiceNames?: readonly string[];
  anchorId: SectionId;
}

/**
 * Service Overrides section of the edit drawer.
 *
 * Field array over `serviceNameOverrides: { driverServiceName, overrideName }[]`.
 * Both fields are free-text inputs in v1 (see {@link serviceOverridesSchema}
 * docstring for the v2 driver-service select TODO).
 *
 * No environment inheritance: `serviceNameOverrides` lives only on the
 * deployment row, so the `environment` prop is unused here aside from
 * threading it through to `ChangedFieldFrame` for the contract.
 */
export function ServiceOverridesSection({
  form,
  initial,
  environment,
  driverServiceNames,
  anchorId,
}: Props) {
  const initialRows = (initial.serviceNameOverrides ??
    []) as ServiceNameOverride[];
  const envRows = (environment.serviceNameOverrides ??
    []) as ServiceNameOverride[];

  const changedCount = useDrawerDiff().entries.filter(
    (e) => e.section === anchorId,
  ).length;

  return (
    <section
      data-section={anchorId}
      id={`${anchorId}-anchor`}
      className="scroll-mt-4"
    >
      <div className="mb-3 flex items-center gap-3">
        <h3
          id={`${anchorId}-heading`}
          className="text-sm font-semibold uppercase tracking-wide text-foreground"
        >
          Services
        </h3>
        {changedCount > 0 && (
          <span
            data-testid={`section-changed-chip-${anchorId}`}
            className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-900 dark:bg-amber-950/40 dark:text-amber-300"
          >
            {changedCount} changed
          </span>
        )}
      </div>

      <form.Field name="serviceNameOverrides" mode="array">
        {(field: any) => {
          const rows: ServiceNameOverride[] = field.state.value ?? [];
          return (
            <div className="space-y-3">
              {rows.length === 0 && (
                <p className="text-xs text-muted-foreground">
                  No service-name overrides.
                </p>
              )}
              {rows.map((_row, index) => {
                const base = `serviceNameOverrides.${index}` as const;
                const initialRow = initialRows[index];
                const envRow = envRows[index];
                return (
                  <div
                    key={`svc-override-${index}`}
                    className="grid grid-cols-[1fr_1fr_auto] items-start gap-2 rounded-md border p-3"
                    data-testid="service-override-row"
                  >
                    <form.Field name={`${base}.driverServiceName`}>
                      {(f: any) => (
                        <ChangedFieldFrame
                          name={`${base}.driverServiceName`}
                          form={form}
                          initial={initialRow?.driverServiceName}
                          environment={envRow?.driverServiceName}
                        >
                          <div className="space-y-1">
                            <Label htmlFor={`svc-driver-${index}`}>
                              Driver service
                            </Label>
                            {driverServiceNames &&
                            driverServiceNames.length > 0 ? (
                              <Select
                                value={
                                  (f.state.value as string | undefined) ?? ""
                                }
                                onValueChange={(v: any) =>
                                  f.handleChange(v === "" ? undefined : v)
                                }
                              >
                                <SelectTrigger
                                  id={`svc-driver-${index}`}
                                  data-testid={`svc-driver-${index}`}
                                >
                                  <SelectValue placeholder="Pick a driver service" />
                                </SelectTrigger>
                                <SelectContent>
                                  {driverServiceNames.map((name) => (
                                    <SelectItem key={name} value={name}>
                                      {name}
                                    </SelectItem>
                                  ))}
                                </SelectContent>
                              </Select>
                            ) : (
                              <Input
                                id={`svc-driver-${index}`}
                                data-testid={`svc-driver-${index}`}
                                value={f.state.value ?? ""}
                                onChange={(e: any) =>
                                  f.handleChange(e.target.value)
                                }
                                onBlur={f.handleBlur}
                                placeholder="declared driver service name"
                                autoComplete="off"
                              />
                            )}
                            {f.state.meta.errors.length > 0 && (
                              <p className="text-xs text-destructive">
                                {String(f.state.meta.errors[0])}
                              </p>
                            )}
                          </div>
                        </ChangedFieldFrame>
                      )}
                    </form.Field>
                    <form.Field name={`${base}.overrideName`}>
                      {(f: any) => (
                        <ChangedFieldFrame
                          name={`${base}.overrideName`}
                          form={form}
                          initial={initialRow?.overrideName}
                          environment={envRow?.overrideName}
                        >
                          <div className="space-y-1">
                            <Label htmlFor={`svc-override-${index}`}>
                              Override name
                            </Label>
                            <Input
                              id={`svc-override-${index}`}
                              data-testid={`svc-override-${index}`}
                              value={f.state.value ?? ""}
                              onChange={(e: any) =>
                                f.handleChange(e.target.value)
                              }
                              onBlur={f.handleBlur}
                              placeholder="my-service"
                              autoComplete="off"
                            />
                            {f.state.meta.errors.length > 0 && (
                              <p className="text-xs text-destructive">
                                {String(f.state.meta.errors[0])}
                              </p>
                            )}
                          </div>
                        </ChangedFieldFrame>
                      )}
                    </form.Field>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      aria-label={`Remove override ${index + 1}`}
                      data-testid={`svc-override-remove-${index}`}
                      onClick={() => field.removeValue(index)}
                      className="mt-6"
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  </div>
                );
              })}
              <Button
                type="button"
                variant="outline"
                size="sm"
                data-testid="add-service-override"
                onClick={() => field.pushValue(emptyRow())}
              >
                Add override
              </Button>
            </div>
          );
        }}
      </form.Field>
    </section>
  );
}
