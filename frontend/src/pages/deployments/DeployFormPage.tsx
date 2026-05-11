import { useParams, useNavigate, Link } from "@tanstack/react-router";
import { useForm, useStore } from "@tanstack/react-form";
import { z } from "zod/v4";
import {
  useListApplicationDriversQuery,
  useDeployMutation,
} from "@/generated/graphql";
import type { ListApplicationDriversQuery } from "@/generated/graphql";
import { useQueryClient } from "@tanstack/react-query";
import { PageLayout } from "@/components/PageLayout";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AlertCircle } from "lucide-react";
import { useState, useMemo, useEffect } from "react";
import { IfRole } from "@/auth/IfRole";

const deployFormSchema = z.object({
  name: z.string().min(1, "Deployment name is required"),
  applicationDriverVersionId: z
    .string()
    .min(1, "Application driver version is required"),
  applicationVersion: z.string().optional(),
});

type DriverVersion = NonNullable<
  ListApplicationDriversQuery["applicationDrivers"]
>[number]["versions"][number];

export default function DeployFormPage() {
  const { environmentId } = useParams({
    from: "/environments/$environmentId/deploy",
  });
  const navigate = useNavigate();
  const {
    data: driversData,
    isLoading,
    error: driversError,
  } = useListApplicationDriversQuery();
  const deployMutation = useDeployMutation();
  const queryClient = useQueryClient();
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [taskResult, setTaskResult] = useState<{
    id: string;
    status: string;
    message?: string | null;
    deploymentId?: string | null;
  } | null>(null);

  const form = useForm({
    defaultValues: {
      name: "",
      applicationDriverVersionId: "",
      applicationVersion: "",
    },
    validators: {
      onSubmit: ({ value }) => {
        const result = deployFormSchema.safeParse(value);
        if (result.success) return undefined;
        const fieldErrors: Record<string, string> = {};
        for (const issue of result.error.issues) {
          const path = issue.path.join(".");
          if (path) fieldErrors[path] = issue.message;
        }
        return { fields: fieldErrors };
      },
    },
    onSubmit: async ({ value }) => {
      setSubmitError(null);
      try {
        const overrides = serviceOverrides
          .map((o) => ({
            driverServiceName: o.driverServiceName.trim(),
            overrideName: o.overrideName.trim(),
          }))
          .filter((o) => o.driverServiceName && o.overrideName);
        const data = await deployMutation.mutateAsync({
          driver: selectedVersion!.driverName,
          name: value.name,
          version: value.applicationVersion || null,
          environmentId,
          parameters:
            Object.keys(dynamicParams).length > 0 ? dynamicParams : null,
          serviceNameOverrides: overrides.length > 0 ? overrides : null,
        });
        queryClient.invalidateQueries({ queryKey: ["GetEnvironment"] });
        if (data.deploy) {
          setTaskResult(data.deploy);
        }
      } catch (err) {
        console.error("[deploy] mutation failed", err);
        setSubmitError(err instanceof Error ? err.message : "Unknown error");
      }
    },
  });

  const isSubmitting = useStore(form.store, (s) => s.isSubmitting);
  const selectedVersionId = useStore(
    form.store,
    (s) => s.values.applicationDriverVersionId,
  );

  const allVersions = useMemo(() => {
    if (!driversData) return [];
    return driversData.applicationDrivers.flatMap((driver) =>
      driver.versions.map((v) => ({ ...v, driverName: driver.name })),
    );
  }, [driversData]);

  const selectedVersion = allVersions.find((v) => v.id === selectedVersionId);

  const hasDefaultVersion = Boolean(selectedVersion?.defaultVersion);

  useEffect(() => {
    if (selectedVersion?.defaultVersion) {
      form.setFieldValue("applicationVersion", selectedVersion.defaultVersion);
    } else {
      form.setFieldValue("applicationVersion", "");
    }
  }, [selectedVersion, form]);

  const [dynamicParams, setDynamicParams] = useState<Record<string, unknown>>(
    {},
  );

  const [serviceOverrides, setServiceOverrides] = useState<
    Array<{ driverServiceName: string; overrideName: string }>
  >([]);

  if (isLoading) return <LoadingState message="Loading drivers..." />;

  if (driversError) {
    return <ErrorState message={driversError.message} />;
  }

  if (taskResult) {
    return (
      <PageLayout
        title="Deployment Submitted"
        breadcrumbs={[
          {
            label: "Environment",
            href: `/environments/${environmentId}`,
          },
          { label: "Deploy" },
        ]}
      >
        <Card className="max-w-lg mx-auto">
          <CardHeader>
            <CardTitle>Deployment Task Created</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground">Status:</span>
              <StatusBadge status={taskResult.status} />
            </div>
            {taskResult.message && (
              <p className="text-sm text-muted-foreground">
                {taskResult.message}
              </p>
            )}
            <div className="flex gap-2">
              <Button
                variant="outline"
                onClick={() =>
                  navigate({
                    to: "/environments/$environmentId",
                    params: { environmentId },
                  })
                }
              >
                Back to Environment
              </Button>
              {taskResult.deploymentId && (
                <Button asChild>
                  <Link
                    to="/environments/$environmentId/deployments/$deploymentId"
                    params={{
                      environmentId,
                      deploymentId: taskResult.deploymentId,
                    }}
                  >
                    View Deployment
                  </Link>
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      </PageLayout>
    );
  }

  return (
    <PageLayout
      title="Deploy Application"
      breadcrumbs={[
        {
          label: "Environment",
          href: `/environments/${environmentId}`,
        },
        { label: "Deploy" },
      ]}
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          e.stopPropagation();
          form.handleSubmit();
        }}
        className="max-w-lg mx-auto space-y-6"
      >
        {submitError && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Deployment failed</AlertTitle>
            <AlertDescription>{submitError}</AlertDescription>
          </Alert>
        )}

        <form.Field name="name">
          {(field) => (
            <div className="space-y-2">
              <Label htmlFor="name">Deployment Name</Label>
              <Input
                id="name"
                placeholder="my-application"
                value={field.state.value}
                onChange={(e) => field.handleChange(e.target.value)}
                onBlur={field.handleBlur}
              />
              {field.state.meta.errors.length > 0 && (
                <p className="text-sm text-destructive">
                  {field.state.meta.errors[0]?.toString()}
                </p>
              )}
            </div>
          )}
        </form.Field>

        <form.Field name="applicationDriverVersionId">
          {(field) => (
            <div className="space-y-2">
              <Label htmlFor="driverVersion">Application Driver Version</Label>
              <Select
                value={field.state.value}
                onValueChange={(value) => {
                  field.handleChange(value);
                  setDynamicParams({});
                }}
              >
                <SelectTrigger data-testid="driver-version-select">
                  {selectedVersion ? (
                    <span>
                      {selectedVersion.driverName} v{selectedVersion.version}
                    </span>
                  ) : (
                    <SelectValue placeholder="Select a driver version" />
                  )}
                </SelectTrigger>
                <SelectContent>
                  {allVersions.map((v) => (
                    <SelectItem key={v.id} value={v.id}>
                      {v.driverName} v{v.version}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {field.state.meta.errors.length > 0 && (
                <p className="text-sm text-destructive">
                  {field.state.meta.errors[0]?.toString()}
                </p>
              )}
            </div>
          )}
        </form.Field>

        <form.Field name="applicationVersion">
          {(field) => (
            <div className="space-y-2">
              <Label htmlFor="applicationVersion">
                Application Version
                {!hasDefaultVersion && (
                  <span className="text-destructive"> *</span>
                )}
              </Label>
              <Input
                id="applicationVersion"
                placeholder={
                  hasDefaultVersion
                    ? (selectedVersion?.defaultVersion ?? "1.0.0")
                    : "1.0.0"
                }
                value={field.state.value}
                onChange={(e) => field.handleChange(e.target.value)}
                onBlur={field.handleBlur}
              />
              {field.state.meta.errors.length > 0 && (
                <p className="text-sm text-destructive">
                  {field.state.meta.errors[0]?.toString()}
                </p>
              )}
              {selectedVersion?.supportedVersions && (
                <p className="text-xs text-muted-foreground">
                  Supported: {selectedVersion.supportedVersions}
                  {hasDefaultVersion &&
                    ` (default: ${selectedVersion.defaultVersion})`}
                </p>
              )}
            </div>
          )}
        </form.Field>

        {selectedVersion && selectedVersion.parameters.length > 0 && (
          <div className="space-y-4">
            <Label className="text-base">Parameters</Label>
            {selectedVersion.parameters.map((param) => (
              <DynamicParameterField
                key={param.name}
                parameter={param}
                value={dynamicParams[param.name]}
                onChange={(value) =>
                  setDynamicParams((prev) => ({
                    ...prev,
                    [param.name]: value,
                  }))
                }
              />
            ))}
          </div>
        )}

        {/* Service name overrides — optional per-driver-service renames. */}
        <div
          role="group"
          aria-labelledby="service-overrides-heading"
          className="space-y-3"
        >
          <Label id="service-overrides-heading" className="text-base">
            Service name overrides
          </Label>
          {serviceOverrides.length === 0 && (
            <p className="text-xs text-muted-foreground">
              Optional. Rename the services the driver publishes — for example,
              run two instances in the same environment under different service
              names.
            </p>
          )}
          {serviceOverrides.map((row, idx) => (
            <div
              key={idx}
              data-testid="service-override-row"
              className="flex gap-2 items-end"
            >
              <div className="flex-1 space-y-1">
                <Label htmlFor={`so-driver-service-${idx}`} className="text-xs">
                  Driver service
                </Label>
                <Input
                  id={`so-driver-service-${idx}`}
                  placeholder="simple-app"
                  value={row.driverServiceName}
                  onChange={(e) =>
                    setServiceOverrides((prev) =>
                      prev.map((r, i) =>
                        i === idx
                          ? { ...r, driverServiceName: e.target.value }
                          : r,
                      ),
                    )
                  }
                />
              </div>
              <div className="flex-1 space-y-1">
                <Label htmlFor={`so-override-${idx}`} className="text-xs">
                  Override name
                </Label>
                <Input
                  id={`so-override-${idx}`}
                  placeholder="intent"
                  value={row.overrideName}
                  onChange={(e) =>
                    setServiceOverrides((prev) =>
                      prev.map((r, i) =>
                        i === idx ? { ...r, overrideName: e.target.value } : r,
                      ),
                    )
                  }
                />
              </div>
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() =>
                  setServiceOverrides((prev) =>
                    prev.filter((_, i) => i !== idx),
                  )
                }
              >
                Remove
              </Button>
            </div>
          ))}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() =>
              setServiceOverrides((prev) => [
                ...prev,
                { driverServiceName: "", overrideName: "" },
              ])
            }
          >
            Add service name override
          </Button>
        </div>

        <div className="flex gap-2">
          <IfRole minimum="READ_WRITE">
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Deploying..." : "Deploy"}
            </Button>
          </IfRole>
          <Button
            type="button"
            variant="outline"
            onClick={() =>
              navigate({
                to: "/environments/$environmentId",
                params: { environmentId },
              })
            }
          >
            Cancel
          </Button>
        </div>
      </form>
    </PageLayout>
  );
}

function DynamicParameterField({
  parameter,
  value,
  onChange,
}: {
  parameter: DriverVersion["parameters"][number];
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const defaultVal = parameter.default as unknown;

  switch (parameter.kind) {
    case "boolean":
      return (
        <div className="flex items-center gap-2">
          <Checkbox
            id={parameter.name}
            checked={(value as boolean) ?? (defaultVal as boolean) ?? false}
            onCheckedChange={(checked) => onChange(checked)}
          />
          <Label htmlFor={parameter.name}>{parameter.label}</Label>
        </div>
      );

    case "select":
      return (
        <div className="space-y-2">
          <Label htmlFor={parameter.name}>{parameter.label}</Label>
          <Select
            value={(value as string) ?? (defaultVal as string) ?? ""}
            onValueChange={(v) => onChange(v)}
          >
            <SelectTrigger>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {parameter.values?.map((v) => (
                <SelectItem key={v} value={v}>
                  {v}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      );

    case "integer":
      return (
        <div className="space-y-2">
          <Label htmlFor={parameter.name}>{parameter.label}</Label>
          <Input
            id={parameter.name}
            type="number"
            value={String(value ?? defaultVal ?? "")}
            onChange={(e) => onChange(parseInt(e.target.value, 10) || 0)}
          />
        </div>
      );

    default:
      return (
        <div className="space-y-2">
          <Label htmlFor={parameter.name}>{parameter.label}</Label>
          <Input
            id={parameter.name}
            value={(value as string) ?? (defaultVal as string) ?? ""}
            onChange={(e) => onChange(e.target.value)}
          />
        </div>
      );
  }
}
