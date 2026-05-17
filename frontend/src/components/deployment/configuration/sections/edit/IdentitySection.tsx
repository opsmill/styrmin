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
import { diff } from "@/lib/config-diff";
import type {
  DriverParameterSchema,
  SectionId,
} from "@/lib/configuration-types";

import { ChangedFieldFrame } from "../../ChangedFieldFrame";

/**
 * Zod schema for the `Identity` slice (currently only `name`). The drawer's
 * aggregated `Form.validate()` composes per-section schemas; exporting one
 * named export per section keeps validation co-located with the editor.
 *
 * Rule comes from data-model.md: `1–64 chars, kebab-case` — matches the
 * project's Kubernetes-name convention (RFC 1123 label).
 */
export const identitySchema = z.object({
  name: z
    .string()
    .min(1, "Deployment name is required")
    .max(64, "Deployment name must be 64 characters or fewer")
    .regex(
      /^[a-z0-9]([-a-z0-9]*[a-z0-9])?$/,
      "Must be lowercase kebab-case (letters, digits, dashes)",
    ),
});

interface Props {
  form: ReactFormLike;
  initial: UpdateDeploymentInput;
  environment: UpdateDeploymentInput;
  driverSchema?: DriverParameterSchema;
  anchorId: SectionId;
  /** Read-only — driver "driverName@version" rendered under the name input. */
  driverLabel: string;
  /** Read-only — current application/app version, rendered with the driver. */
  appVersion: string;
}

/**
 * Identity section of the edit drawer.
 *
 * Editable fields:
 *  - `name` — validated by {@link identitySchema}.
 *
 * Read-only display:
 *  - Driver name + version
 *  - App version
 *
 * Per spec (FR-014), driver and app version are not mutated from this
 * surface — they live behind the existing Upgrade button on the deployment
 * detail page. The drawer surfaces them so the operator has the identifying
 * context next to the renameable handle without context-switching.
 */
export function IdentitySection({
  form,
  initial,
  environment,
  anchorId,
  driverLabel,
  appVersion,
}: Props) {
  const changedCount = useStore(form.store, (state) => {
    const values = (state as { values: UpdateDeploymentInput }).values;
    return diff(initial, values, [] as DriverParameterSchema).entries.filter(
      (e) => e.section === anchorId,
    ).length;
  });

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
          Identity
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
        <form.Field name="name">
          {(field: any) => (
            <ChangedFieldFrame
              name="name"
              form={form}
              initial={initial.name}
              environment={environment.name}
            >
              <div className="space-y-1">
                <Label htmlFor="identity-name">Deployment name</Label>
                <Input
                  id="identity-name"
                  data-testid="identity-name-input"
                  value={(field.state.value as string | undefined) ?? ""}
                  onChange={(e) => field.handleChange(e.target.value)}
                  onBlur={field.handleBlur}
                  placeholder="my-deployment"
                  autoComplete="off"
                />
                {field.state.meta.errors.length > 0 && (
                  <p className="text-xs text-destructive">
                    {String(field.state.meta.errors[0])}
                  </p>
                )}
              </div>
            </ChangedFieldFrame>
          )}
        </form.Field>

        <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
          <dl className="grid grid-cols-1 gap-y-2 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
                Application driver
              </dt>
              <dd
                data-testid="identity-driver-label"
                className="font-mono text-sm text-slate-900"
              >
                {driverLabel || "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs font-medium uppercase tracking-wide text-slate-500">
                Application version
              </dt>
              <dd
                data-testid="identity-app-version"
                className="font-mono text-sm text-slate-900"
              >
                {appVersion || "—"}
              </dd>
            </div>
          </dl>
          <p className="mt-2 text-xs italic text-slate-500">
            Use the Upgrade button on the deployment header to change these.
          </p>
        </div>
      </div>
    </section>
  );
}
