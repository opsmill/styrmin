<!-- Extracted from specs/001-tanstack-form-migration on 2026-04-26 -->

## Frontend Forms

### Overview

The frontend uses **TanStack Form** (`@tanstack/react-form`) for every form component:

- the Load driver drawer;
- the Create and Detail backup storage location forms;
- the Create cluster and Edit cluster dialogs;
- the Create environment and Clone environment dialogs;
- the Deploy form;
- the deployment configuration edit drawer.

Most of them follow the same pattern: a Zod schema declares shape and constraints, `<form.Field>` binds inputs to form state, and submission calls a TanStack Query mutation.

<!-- Extracted from specs/021-cluster-config-update on 2026-10-13 -->

TanStack Form 1.28+ accepts Zod schemas directly via Standard Schema. There is **no `@tanstack/zod-form-adapter`** dependency — it isn't needed at this version.

### Hook Setup

```tsx
import { useForm, useStore } from "@tanstack/react-form";

const form = useForm({
  defaultValues: { name: "", endpoint: "" },
  validators: { onSubmit: createBslSchema }, // full Zod schema, including .refine()
  onSubmit: async ({ value }) => {
    await createBsl.mutateAsync(value);
    queryClient.invalidateQueries({ queryKey: useListBslQuery.getKey() });
  },
});
```

### Field Binding

A single `<form.Field>` render-prop component handles **both** uncontrolled inputs and Radix/Base UI controlled primitives. There is no equivalent of RHF's `register` vs `Controller` split.

**Plain input:**

```tsx
<form.Field name="name" validators={{ onChange: z.string().min(1) }}>
  {(field) => (
    <Input
      value={field.state.value}
      onChange={(e) => field.handleChange(e.target.value)}
    />
  )}
</form.Field>
```

**Controlled UI primitive (Select, Checkbox):**

```tsx
<form.Field name="clusterId" validators={{ onChange: z.string().min(1) }}>
  {(field) => (
    <Select
      items={clusterOptions}
      value={field.state.value}
      onValueChange={field.handleChange}
    >
      {/* options, rendered from clusterOptions */}
    </Select>
  )}
</form.Field>
```

Per-field errors live at `field.state.meta.errors`.

### Reactive Subscriptions

The standalone `useStore` from `@tanstack/react-form`, applied to `form.store`, replaces RHF's `watch` and `formState` reads. The selector pattern keeps re-render scoping tight.

```tsx
import { useStore } from "@tanstack/react-form";

const isSubmitting = useStore(form.store, (s) => s.isSubmitting);
const dedicatedIngressEnabled = useStore(
  form.store,
  (s) => s.values.dedicated_ingress_enabled,
);

return (
  <>
    {dedicatedIngressEnabled && <IngressFields />}
    <Button disabled={isSubmitting}>Submit</Button>
  </>
);
```

### Cross-Field Validation

Zod `.refine()` works as form-level validation when the full schema is passed via `validators.onSubmit`. Per-field validators continue to use simpler Zod types for instant feedback.

The cluster forms keep their cross-field rules in one `superRefine` function, so the create and
edit dialogs share them (`components/cluster/ClusterConfigFields.helpers.ts`):

```ts
export function refineClusterConfig(
  data: ClusterConfigFormValues,
  ctx: z.RefinementCtx,
): void {
  if (data.standard_storage_enabled && !data.standard_storage_class) {
    ctx.addIssue({
      code: "custom",
      message: "Storage class is required when standard storage is enabled",
      path: ["standard_storage_class"],
    });
  }
  // … the same for fast storage, the external URL port and the NodePort
}

export const clusterConfigSchema =
  z.object(clusterConfigShape).superRefine(refineClusterConfig);

// The Create cluster dialog adds its `name` field to the same shape and rules.
const createClusterSchema = z
  .object({ name: z.string().min(1, "Cluster name is required"), ...clusterConfigShape })
  .superRefine(refineClusterConfig);
```

The two cluster dialogs pass a function to `validators.onSubmit` instead of the schema itself.
`schemaFieldErrors(schema, value)` runs `safeParse` and returns the issues in the
`{ fields: { "<path>": "<message>" } }` shape that a TanStack Form validator returns, or
`undefined` when the values are valid:

```ts
validators: {
  onSubmit: ({ value }) => schemaFieldErrors(createClusterSchema, value),
},
```

<!-- Extracted from specs/021-cluster-config-update on 2026-10-13 -->

### Dynamic Fields Outside the Schema

The Deploy Form renders runtime-discovered driver parameters whose shape depends on the selected driver. These are **intentionally not modeled in the form schema** — they live in plain `useState` and are merged into the mutation payload at submit time. The three statically-known fields (`name`, `applicationDriverVersionId`, `applicationVersion`) remain TanStack Form fields.

This split keeps the schema honest (it describes only what is statically known) and avoids modeling variable-shape data as a TanStack Form field array.

### Dialog Reset

Forms inside dialogs call `form.reset()` from the dialog's `onOpenChange` to restore default values and clear errors when the dialog closes.

```tsx
<Dialog onOpenChange={(open) => { if (!open) form.reset(); }}>
```

### Cluster config form (create and edit)

`ClusterConfigFields` (`components/cluster/ClusterConfigFields.tsx`) renders the cluster config
fields of both the Create cluster dialog (`pages/settings/CreateClusterDialog.tsx`) and the Edit
cluster dialog (`pages/clusters/EditClusterDialog.tsx`). The form edits the config in its stored
format: snake_case keys and stored enum values such as `http` and `NodeExternalIP`.
`configToFormValues` and `formValuesToConfig` convert between the stored config and the form
values.

The cluster detail page shows the Edit button only to administrators, through
`<IfRole minimum="ADMIN">`. The Edit dialog keeps a copy of the config it opened with and has
three steps:

1. Edit: the form. Submitting it builds the full config and calls `updateCluster` with
   `dryRun: true`.
2. Review (`ClusterUpdateReview` in `pages/clusters/ClusterUpdateSummary.tsx`): the values that
   change and the deployments that saving would redeploy. It warns when:
   - the FQDN suffix changes, because the URLs of the applications that take it change;
   - a storage class changes, because Kubernetes refuses to change the storage class of an
     existing volume claim, so deployments whose StatefulSets use it become `FAILED`;
   - dedicated ingress controllers are created or removed.
3. Result (`ClusterUpdateResult`): after `updateCluster` with `dryRun: false`. The dialog then
   invalidates the `GetCluster` query of that cluster.

`mergeFormValuesIntoConfig(stored, values)` builds the config to save from the form values and
the stored config, because `updateCluster` replaces the whole config:

- Top-level keys that the form does not show, such as `db_size` and
  `backup_ttl`, keep their stored value.
- `dedicated_ingress.service` fields that the form does not show, such as `annotations` and
  `load_balancer_ip`, keep their stored value.
- A value cleared in the form is removed.
- When the IP families are the same set as the stored ones, the stored order is kept, so saving
  does not change the controller.

`clusterConfigToInput` (`lib/cluster-input.ts`) converts the stored config to
`UpdateClusterInput`: camelCase keys and GraphQL enum names. It maps each field by hand. A field
left out would be removed by every save from the Edit dialog, so two checks report one (#454):

- The function must name every key of `UpdateClusterInput` and of its nested inputs, so the
  compiler reports a key that it leaves out.
- `lib/cluster-input.full-config.json` holds a stored config that sets every field and the input
  it converts to. The backend test `test_full_config_sets_every_cluster_config_field` fails when
  the stored config does not set every `ClusterConfig` field. `lib/cluster-input.test.ts` fails
  when `clusterConfigToInput` does not convert the stored config to the input.

### Service ingress fields (deploy form and configuration drawer)

<!-- Extracted from specs/033-service-ingress-override on 2026-11-10 -->

`ServiceIngressFields` (`components/deployment/configuration/ServiceIngressFields.tsx`) renders the ingress class and the FQDN suffix of each service whose `scope` is `external`, with a **Clear** button for each service. A service that is not external gets no field, because Styrmin builds no Ingress for it and the backend refuses an override on it (`SERVICE_INGRESS_NOT_BUILT`). The component returns `null` when no service is external. Both forms use it, so they offer the same fields, labels (`Ingress class for <service>`, `FQDN suffix for <service>`) and validation ([ADR-090](../../adr/0090-styrmin-builds-the-ingress-of-an-external-service.md)).

| Place | Where the services come from | State |
|-------|------------------------------|-------|
| Deploy form (`pages/deployments/DeployFormPage.tsx`), group `service-ingress-section` | `services { name scope kind }` of the selected driver version, added to `list_application_drivers.graphql` | `serviceIngress` in `useState`, outside the form schema like the other dynamic fields. Reset when the driver version changes. |
| Configuration drawer, section **Service overrides** (`ServiceOverridesSection`, group **Service ingress overrides**) | `deployment.deployedServices` (with `scope`), passed as the `services` prop by `ConfigEditDrawer` | TanStack Form field `services` of the drawer's form |

- Validation mirrors the backend: `ingressClassError` in `lib/ingress-class.ts` (a Kubernetes object name, at most 253 characters) and `fqdnSuffixError` in `lib/fqdn-suffix.ts` (a DNS name, labels of 1 to 63 characters, at most 253 in total). An empty field is not an error: it means the resolved value applies. An invalid value sets `aria-invalid` on its input and names the rule in the message that the input is described by. Keep the two files in step with `validate_service_ingress_class` and `validate_service_fqdn_suffix` in `context/models/config.py`.
- `DrawerInvalidFields` (`DrawerDiffContext.tsx`) has `services`, the services whose FQDN suffix is invalid, and `serviceClasses`, the services whose ingress class is invalid. While either is not empty, the footer disables **Review & apply** with a hint that names the services. The deploy form disables **Deploy** and shows `deploy-blocked-reason` for the same cases.
- `servicesFormToInput` (`lib/deployment-input.ts`) maps the rows to `ServiceConfigInput` on submit. An emptied field holds `""`, which the backend rejects, so the function leaves the field out, and a row with no value is dropped. `deploymentConfigToInput` maps the stored `services` back to rows. `updateDeployment` replaces the whole stored config, so a projection that leaves `services` out would clear every stored override on the next save of any other field.
- The review dialog lists each change as `Service "<name>" ingress class` or `Service "<name>" FQDN suffix` (`diffServices` in `lib/config-diff.ts`), with the impact rules in `lib/impact-rules.ts`.
- The read-only **Networking** summary (`NetworkingSummary`) lists each external service with its effective class and host, marked **Overridden** or **Inherited**, from `ingressClass`, `ingressClassOverridden`, `humanReadableFqdn` and `fqdnSuffixOverridden` of `deployedServices`.

<!-- Extracted from specs/021-cluster-config-update on 2026-10-13 -->

### Form Tests

No form-specific tests existed before the migration, so none were updated. Tests for utility components (ErrorState, LoadingState, StatusBadge) were unaffected. Adding form-level test coverage is outstanding follow-up work.

### What Was Replaced

| Concept | Before (React Hook Form) | After (TanStack Form) |
|---------|--------------------------|-----------------------|
| Hook | `useForm({ resolver: zodResolver(schema) })` | `useForm({ validators: { onSubmit: schema } })` (Standard Schema, no adapter) |
| Plain field | `{...register("name")}` | `<form.Field>{(field) => ...}</form.Field>` |
| Controlled field | `<Controller name=... render={...}/>` | (same `<form.Field>` — unified) |
| Watch value | `watch("name")` | `useStore(form.store, (s) => s.values.name)` |
| Submitting state | `formState.isSubmitting` | `useStore(form.store, (s) => s.isSubmitting)` |
| Imperative set | `setValue("name", v)` | `form.setFieldValue("name", v)` |
| Reset | `reset()` | `form.reset()` |
