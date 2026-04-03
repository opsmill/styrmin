import { useParams, useNavigate, Link } from "@tanstack/react-router";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
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

const deployFormSchema = z.object({
  name: z.string().min(1, "Deployment name is required"),
  applicationDriverVersionId: z
    .string()
    .min(1, "Application driver version is required"),
  applicationVersion: z.string().optional(),
});

type DeployFormValues = z.infer<typeof deployFormSchema>;

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

  const {
    register,
    handleSubmit,
    control,
    watch,
    setValue,
    formState: { errors, isSubmitting },
  } = useForm<DeployFormValues>({
    resolver: zodResolver(deployFormSchema),
    defaultValues: {
      name: "",
      applicationDriverVersionId: "",
      applicationVersion: "",
    },
  });

  const selectedVersionId = watch("applicationDriverVersionId");

  const allVersions = useMemo(() => {
    if (!driversData) return [];
    return driversData.applicationDrivers.flatMap((driver) =>
      driver.versions.map((v) => ({ ...v, driverName: driver.name })),
    );
  }, [driversData]);

  const selectedVersion = useMemo(
    () => allVersions.find((v) => v.id === selectedVersionId),
    [allVersions, selectedVersionId],
  );

  const hasDefaultVersion = Boolean(selectedVersion?.defaultVersion);

  useEffect(() => {
    if (selectedVersion?.defaultVersion) {
      setValue("applicationVersion", selectedVersion.defaultVersion);
    } else {
      setValue("applicationVersion", "");
    }
  }, [selectedVersion, setValue]);

  const [dynamicParams, setDynamicParams] = useState<Record<string, unknown>>(
    {},
  );

  const onSubmit = async (values: DeployFormValues) => {
    setSubmitError(null);
    try {
      const data = await deployMutation.mutateAsync({
        driver: selectedVersion!.driverName,
        name: values.name,
        version: values.applicationVersion || null,
        environmentId,
        parameters:
          Object.keys(dynamicParams).length > 0 ? dynamicParams : null,
      });
      queryClient.invalidateQueries({ queryKey: ["GetEnvironment"] });
      if (data.deploy) {
        setTaskResult(data.deploy);
      }
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Unknown error");
    }
  };

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
        onSubmit={handleSubmit(onSubmit)}
        className="max-w-lg mx-auto space-y-6"
      >
        {submitError && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Deployment failed</AlertTitle>
            <AlertDescription>{submitError}</AlertDescription>
          </Alert>
        )}

        <div className="space-y-2">
          <Label htmlFor="name">Deployment Name</Label>
          <Input id="name" placeholder="my-application" {...register("name")} />
          {errors.name && (
            <p className="text-sm text-destructive">{errors.name.message}</p>
          )}
        </div>

        <div className="space-y-2">
          <Label htmlFor="driverVersion">Application Driver Version</Label>
          <Controller
            name="applicationDriverVersionId"
            control={control}
            render={({ field }) => (
              <Select
                value={field.value}
                onValueChange={(value) => {
                  field.onChange(value);
                  setDynamicParams({});
                }}
              >
                <SelectTrigger>
                  <SelectValue placeholder="Select a driver version" />
                </SelectTrigger>
                <SelectContent>
                  {allVersions.map((v) => (
                    <SelectItem key={v.id} value={v.id}>
                      {v.driverName} v{v.version}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          />
          {errors.applicationDriverVersionId && (
            <p className="text-sm text-destructive">
              {errors.applicationDriverVersionId.message}
            </p>
          )}
        </div>

        <div className="space-y-2">
          <Label htmlFor="applicationVersion">
            Application Version
            {!hasDefaultVersion && <span className="text-destructive"> *</span>}
          </Label>
          <Input
            id="applicationVersion"
            placeholder={
              hasDefaultVersion
                ? (selectedVersion?.defaultVersion ?? "1.0.0")
                : "1.0.0"
            }
            {...register("applicationVersion")}
          />
          {errors.applicationVersion && (
            <p className="text-sm text-destructive">
              {errors.applicationVersion.message}
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

        <div className="flex gap-2">
          <Button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Deploying..." : "Deploy"}
          </Button>
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
