// Section components bind to arbitrary dotted sub-paths under
// `UpdateDeploymentInput`; the TanStack Form per-path generic narrowing is
// not usable across the full schema, so `form.Field` children are typed as
// `any` and validated through the section's Zod schema and runtime guards
// inside each input.
/* eslint-disable @typescript-eslint/no-explicit-any */
import { useStore } from "@tanstack/react-form";
import { z } from "zod";

import type { ReactFormLike } from "./types";

import type { UpdateDeploymentInput } from "@/generated/graphql";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { diff } from "@/lib/config-diff";
import type {
  DriverParameterSchema,
  SectionId,
} from "@/lib/configuration-types";

import { ChangedFieldFrame } from "../../ChangedFieldFrame";

const K8S_NAME = /^[a-z]([-a-z0-9]*[a-z0-9])?$/;
const DB_SIZES = ["small", "medium", "large", "xlarge"] as const;
type DbSize = (typeof DB_SIZES)[number];

/**
 * Zod schema for the `Storage & Runtime` slice.
 *
 * Rules (data-model.md "Storage & Runtime" row):
 *  - `dbSize` matches the enum {small,medium,large,xlarge}. Persisted as a
 *    free-form string on the backend (no GraphQL enum); we constrain client-
 *    side because the UI offers only these four values.
 *  - `standardStorage.storageClass` must be a non-empty Kubernetes name
 *    (RFC 1035 label).
 *  - `nodeSelector` is a free-form selector expression; we only require it
 *    be a string (parser-level validation lives on the backend).
 */
export const storageRuntimeSchema = z.object({
  dbSize: z.enum(DB_SIZES).optional(),
  standardStorage: z
    .object({
      storageClass: z
        .string()
        .trim()
        .min(1, "Storage class is required")
        .regex(K8S_NAME, "Must be a valid Kubernetes name (RFC 1035)"),
    })
    .optional(),
  nodeSelector: z.string().optional(),
});

interface Props {
  form: ReactFormLike;
  initial: UpdateDeploymentInput;
  environment: UpdateDeploymentInput;
  driverSchema?: DriverParameterSchema;
  anchorId: SectionId;
}

/**
 * Storage & Runtime section of the edit drawer. Three fields:
 *
 *  - `dbSize` — enum select used as a hint by managed-database components.
 *  - `standardStorage.storageClass` — name of the default Kubernetes
 *    `StorageClass` for the deployment.
 *  - `nodeSelector` — node-selector expression applied to every pod.
 */
export function StorageRuntimeSection({
  form,
  initial,
  environment,
  anchorId,
}: Props) {
  const changedCount = useStore(
    form.store,
    (state: any) =>
      diff(initial, state.values, [] as DriverParameterSchema).entries.filter(
        (e: any) => e.section === anchorId,
      ).length,
  );

  return (
    <section
      data-section={anchorId}
      id={`${anchorId}-anchor`}
      className="scroll-mt-4"
    >
      <div className="mb-3 flex items-center gap-3">
        <h3
          id={`${anchorId}-heading`}
          className="text-sm font-semibold uppercase tracking-wide text-slate-700"
        >
          Storage &amp; Runtime
        </h3>
        {changedCount > 0 && (
          <span
            data-testid={`section-changed-chip-${anchorId}`}
            className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-900"
          >
            {changedCount} changed
          </span>
        )}
      </div>

      <div className="space-y-4">
        {/* DB size */}
        <form.Field name="dbSize">
          {(f: any) => (
            <ChangedFieldFrame
              name="dbSize"
              form={form}
              initial={initial.dbSize}
              environment={environment.dbSize}
            >
              <div className="space-y-1">
                <Label htmlFor="storage-db-size">Database size</Label>
                <Select
                  value={(f.state.value as DbSize | undefined) ?? ""}
                  onValueChange={(v: any) =>
                    f.handleChange(v === "" ? undefined : (v as DbSize))
                  }
                >
                  <SelectTrigger
                    id="storage-db-size"
                    data-testid="storage-db-size"
                  >
                    <SelectValue placeholder="Not set" />
                  </SelectTrigger>
                  <SelectContent>
                    {DB_SIZES.map((size) => (
                      <SelectItem key={size} value={size}>
                        {size}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </ChangedFieldFrame>
          )}
        </form.Field>

        {/* Standard storage class */}
        <form.Field name="standardStorage.storageClass">
          {(f: any) => (
            <ChangedFieldFrame
              name="standardStorage.storageClass"
              form={form}
              initial={initial.standardStorage?.storageClass}
              environment={environment.standardStorage?.storageClass}
            >
              <div className="space-y-1">
                <Label htmlFor="storage-class">Storage class</Label>
                <Input
                  id="storage-class"
                  data-testid="storage-class"
                  value={f.state.value ?? ""}
                  onChange={(e: any) =>
                    f.handleChange(
                      e.target.value === "" ? undefined : e.target.value,
                    )
                  }
                  onBlur={f.handleBlur}
                  placeholder="e.g. standard-rwo"
                  autoComplete="off"
                />
              </div>
            </ChangedFieldFrame>
          )}
        </form.Field>

        {/* Node selector */}
        <form.Field name="nodeSelector">
          {(f: any) => (
            <ChangedFieldFrame
              name="nodeSelector"
              form={form}
              initial={initial.nodeSelector}
              environment={environment.nodeSelector}
            >
              <div className="space-y-1">
                <Label htmlFor="storage-node-selector">Node selector</Label>
                <Input
                  id="storage-node-selector"
                  data-testid="storage-node-selector"
                  value={f.state.value ?? ""}
                  onChange={(e: any) =>
                    f.handleChange(
                      e.target.value === "" ? undefined : e.target.value,
                    )
                  }
                  onBlur={f.handleBlur}
                  placeholder="e.g. disktype=ssd"
                  autoComplete="off"
                />
              </div>
            </ChangedFieldFrame>
          )}
        </form.Field>
      </div>
    </section>
  );
}
