// The create and edit dialogs own forms of different shapes that share these
// field names, so `form` is typed loosely, as in the deployment edit sections.
/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useRef, type ReactNode } from "react";
import { useStore } from "@tanstack/react-form";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  CLUSTER_CONFIG_LABELS as LABELS,
  DEFAULT_DEDICATED_INGRESS_IMPLEMENTATION,
  DEFAULT_DEDICATED_INGRESS_TYPE,
  DEFAULT_EXTERNAL_URL_SCHEME,
  DEFAULT_INGRESS_CLASS,
  DEFAULT_INGRESS_SERVICE_TYPE,
  DEFAULT_RUNTIME_CLASS,
} from "./ClusterConfigFields.helpers";

interface ClusterConfigFieldsProps {
  /** A TanStack Form whose values hold every `ClusterConfigFormValues` key. */
  form: any;
}

const SELECT_CLASS =
  "flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring aria-[invalid=true]:border-destructive";

function firstError(field: any): string | undefined {
  return field.state.meta.errors[0]?.toString();
}

/** `aria-invalid` and `aria-describedby` for a control, from its hint and its first error. */
function describedBy(
  id: string,
  { hint, error }: { hint?: boolean; error?: string },
) {
  const ids = [hint && `${id}-hint`, error && `${id}-error`].filter(Boolean);
  return {
    "aria-invalid": error ? true : undefined,
    "aria-describedby": ids.length > 0 ? ids.join(" ") : undefined,
  };
}

function Hint({ id, children }: { id: string; children: ReactNode }) {
  return (
    <p id={`${id}-hint`} className="text-xs text-muted-foreground">
      {children}
    </p>
  );
}

function FieldError({ id, error }: { id: string; error?: string }) {
  if (!error) return null;
  return (
    <p id={`${id}-error`} className="text-sm text-destructive">
      {error}
    </p>
  );
}

interface TextFieldProps {
  field: any;
  id: string;
  label: string;
  placeholder?: string;
  hint?: ReactNode;
  type?: "text" | "number";
}

function TextField({
  field,
  id,
  label,
  placeholder,
  hint,
  type = "text",
}: TextFieldProps) {
  const error = firstError(field);
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        type={type}
        {...(type === "number" ? { min: 1, max: 65535 } : {})}
        placeholder={placeholder}
        value={field.state.value ?? ""}
        onChange={(e) => field.handleChange(e.target.value)}
        onBlur={field.handleBlur}
        {...describedBy(id, { hint: hint !== undefined, error })}
      />
      {hint !== undefined && <Hint id={id}>{hint}</Hint>}
      <FieldError id={id} error={error} />
    </div>
  );
}

interface SelectFieldProps {
  field: any;
  id: string;
  label: string;
  /** The label of the empty value, which leaves the key unset. */
  emptyLabel: string;
  options: readonly string[];
  onChange?: (value: string) => void;
}

/** A select that also lists a stored value it does not know, so saving keeps it. */
function SelectField({
  field,
  id,
  label,
  emptyLabel,
  options,
  onChange,
}: SelectFieldProps) {
  const value: string = field.state.value ?? "";
  const error = firstError(field);
  const shown =
    value && !options.includes(value) ? [...options, value] : options;
  return (
    <div className="space-y-2">
      <Label htmlFor={id}>{label}</Label>
      <select
        id={id}
        className={SELECT_CLASS}
        value={value}
        onChange={(e) => {
          field.handleChange(e.target.value);
          onChange?.(e.target.value);
        }}
        onBlur={field.handleBlur}
        {...describedBy(id, { error })}
      >
        <option value="">{emptyLabel}</option>
        {shown.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
      <FieldError id={id} error={error} />
    </div>
  );
}

function CheckboxField({
  field,
  id,
  label,
  className,
}: {
  field: any;
  id: string;
  label: string;
  className?: string;
}) {
  return (
    <div className="flex items-center gap-2">
      <Checkbox
        id={id}
        checked={field.state.value}
        onCheckedChange={(checked) => field.handleChange(checked === true)}
      />
      <Label htmlFor={id} className={className}>
        {label}
      </Label>
    </div>
  );
}

/** Move the focus to the first field with an error after a submission fails. */
function useFocusFirstInvalidField(form: any) {
  const containerRef = useRef<HTMLDivElement>(null);
  const attempts = useStore(form.store, (s: any) => s.submissionAttempts);
  const isValid = useStore(form.store, (s: any) => s.isValid as boolean);
  useEffect(() => {
    if (attempts === 0 || isValid) return;
    containerRef.current
      ?.querySelector<HTMLElement>('[aria-invalid="true"]')
      ?.focus();
  }, [attempts, isValid]);
  return containerRef;
}

/** The cluster config fields of the create and edit cluster dialogs. */
export function ClusterConfigFields({ form }: ClusterConfigFieldsProps) {
  const containerRef = useFocusFirstInvalidField(form);
  const dedicatedIngressEnabled = useStore(
    form.store,
    (s: any) => s.values.dedicated_ingress_enabled as boolean,
  );
  const dedicatedIngressServiceType = useStore(
    form.store,
    (s: any) => s.values.dedicated_ingress_service_type as string,
  );
  const standardStorageEnabled = useStore(
    form.store,
    (s: any) => s.values.standard_storage_enabled as boolean,
  );
  const fastStorageEnabled = useStore(
    form.store,
    (s: any) => s.values.fast_storage_enabled as boolean,
  );

  return (
    <div ref={containerRef} className="space-y-4">
      <form.Field name="ingress_class">
        {(field: any) => (
          <TextField
            field={field}
            id="cluster-ingress-class"
            label={LABELS.ingress_class}
            placeholder={DEFAULT_INGRESS_CLASS}
            hint={`Leave empty to use ${DEFAULT_INGRESS_CLASS}.`}
          />
        )}
      </form.Field>

      <form.Field name="fqdn_suffix">
        {(field: any) => (
          <TextField
            field={field}
            id="cluster-fqdn-suffix"
            label={LABELS.fqdn_suffix}
            placeholder="example.com"
          />
        )}
      </form.Field>

      <form.Field name="runtime_class">
        {(field: any) => (
          <TextField
            field={field}
            id="cluster-runtime-class"
            label={LABELS.runtime_class}
            placeholder={DEFAULT_RUNTIME_CLASS}
            hint={`Leave empty to use ${DEFAULT_RUNTIME_CLASS}.`}
          />
        )}
      </form.Field>

      <form.Field name="external_url_scheme">
        {(field: any) => (
          <SelectField
            field={field}
            id="cluster-external-url-scheme"
            label={LABELS.external_url_scheme}
            emptyLabel={`Default (${DEFAULT_EXTERNAL_URL_SCHEME})`}
            options={["http", "https"]}
          />
        )}
      </form.Field>

      <form.Field name="external_url_port">
        {(field: any) => (
          <TextField
            field={field}
            id="cluster-external-url-port"
            type="number"
            label={LABELS.external_url_port}
            placeholder="e.g. 8080"
            hint="Leave empty to use the scheme's port (80 or 443)."
          />
        )}
      </form.Field>

      <form.Field name="external_dns_endpoints_type">
        {(field: any) => (
          <SelectField
            field={field}
            id="cluster-external-dns-endpoints-type"
            label={LABELS.external_dns_endpoints_type}
            emptyLabel="Not set (no annotation)"
            options={["NodeExternalIP", "ClusterIP"]}
          />
        )}
      </form.Field>

      <div className="space-y-3 rounded-md border p-3">
        <form.Field name="dedicated_ingress_enabled">
          {(field: any) => (
            <CheckboxField
              field={field}
              id="cluster-dedicated-ingress"
              label={LABELS.dedicated_ingress}
              className="font-medium"
            />
          )}
        </form.Field>
        {dedicatedIngressEnabled && (
          <div className="space-y-3 ml-6">
            <form.Field name="dedicated_ingress_implementation">
              {(field: any) => (
                <TextField
                  field={field}
                  id="cluster-di-impl"
                  label={LABELS.implementation}
                  placeholder={DEFAULT_DEDICATED_INGRESS_IMPLEMENTATION}
                  hint={`Leave empty to use ${DEFAULT_DEDICATED_INGRESS_IMPLEMENTATION}.`}
                />
              )}
            </form.Field>
            <form.Field name="dedicated_ingress_type">
              {(field: any) => (
                <SelectField
                  field={field}
                  id="cluster-di-type"
                  label={LABELS.routing_type}
                  emptyLabel={`Default (${DEFAULT_DEDICATED_INGRESS_TYPE})`}
                  options={["ingress", "gateway"]}
                />
              )}
            </form.Field>
            <form.Field name="dedicated_ingress_service_type">
              {(field: any) => (
                <SelectField
                  field={field}
                  id="cluster-di-service-type"
                  label={LABELS.service_type}
                  emptyLabel={`Default (${DEFAULT_INGRESS_SERVICE_TYPE})`}
                  options={["LoadBalancer", "ClusterIP", "NodePort"]}
                  onChange={(next) => {
                    if (next !== "NodePort") {
                      form.setFieldValue(
                        "dedicated_ingress_service_node_port",
                        "",
                      );
                    }
                  }}
                />
              )}
            </form.Field>
            {dedicatedIngressServiceType === "NodePort" && (
              <form.Field name="dedicated_ingress_service_node_port">
                {(field: any) => (
                  <TextField
                    field={field}
                    id="cluster-di-service-node-port"
                    type="number"
                    label={LABELS.node_port}
                    placeholder="e.g. 32443"
                  />
                )}
              </form.Field>
            )}
            <form.Field name="dedicated_ingress_service_external_traffic_policy">
              {(field: any) => (
                <SelectField
                  field={field}
                  id="cluster-di-service-etp"
                  label={LABELS.external_traffic_policy}
                  emptyLabel="Not set"
                  options={["Cluster", "Local"]}
                />
              )}
            </form.Field>
            <fieldset className="space-y-2">
              <legend className="text-sm font-medium leading-none">
                {LABELS.ip_families}
              </legend>
              <div className="flex items-center gap-4">
                <form.Field name="dedicated_ingress_service_ip_family_ipv4">
                  {(field: any) => (
                    <CheckboxField
                      field={field}
                      id="cluster-di-service-ipv4"
                      label="IPv4"
                    />
                  )}
                </form.Field>
                <form.Field name="dedicated_ingress_service_ip_family_ipv6">
                  {(field: any) => (
                    <CheckboxField
                      field={field}
                      id="cluster-di-service-ipv6"
                      label="IPv6"
                    />
                  )}
                </form.Field>
              </div>
            </fieldset>
            <form.Field name="dedicated_ingress_service_ip_family_policy">
              {(field: any) => (
                <SelectField
                  field={field}
                  id="cluster-di-service-ip-family-policy"
                  label={LABELS.ip_family_policy}
                  emptyLabel="Not set"
                  options={[
                    "SingleStack",
                    "PreferDualStack",
                    "RequireDualStack",
                  ]}
                />
              )}
            </form.Field>
          </div>
        )}
      </div>

      <div className="space-y-3 rounded-md border p-3">
        <form.Field name="standard_storage_enabled">
          {(field: any) => (
            <CheckboxField
              field={field}
              id="cluster-standard-storage"
              label={LABELS.standard_storage}
              className="font-medium"
            />
          )}
        </form.Field>
        {standardStorageEnabled && (
          <div className="space-y-3 ml-6">
            <form.Field name="standard_storage_class">
              {(field: any) => (
                <TextField
                  field={field}
                  id="cluster-sc"
                  label={LABELS.standard_storage_class}
                  placeholder="e.g. ebs-gp3"
                />
              )}
            </form.Field>
          </div>
        )}
      </div>

      <div className="space-y-3 rounded-md border p-3">
        <form.Field name="fast_storage_enabled">
          {(field: any) => (
            <CheckboxField
              field={field}
              id="cluster-fast-storage"
              label={LABELS.fast_storage}
              className="font-medium"
            />
          )}
        </form.Field>
        {fastStorageEnabled && (
          <div className="space-y-3 ml-6">
            <form.Field name="fast_storage_class">
              {(field: any) => (
                <TextField
                  field={field}
                  id="cluster-fast-sc"
                  label={LABELS.fast_storage_class}
                  placeholder="e.g. nvme-local"
                />
              )}
            </form.Field>
          </div>
        )}
      </div>
    </div>
  );
}
