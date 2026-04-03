import { useNavigate } from "@tanstack/react-router";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod/v4";
import {
  useLoadLocalDriverMutation,
  useLoadRemoteDriverMutation,
} from "@/generated/graphql";
import { useQueryClient } from "@tanstack/react-query";
import { PageLayout } from "@/components/PageLayout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertCircle } from "lucide-react";
import { useState } from "react";

const localSchema = z.object({
  path: z.string().min(1, "Path is required"),
});

const remoteSchema = z.object({
  repositoryUrl: z.string().min(1, "Repository URL is required"),
  branch: z.string().min(1, "Branch is required"),
});

type LocalFormValues = z.infer<typeof localSchema>;
type RemoteFormValues = z.infer<typeof remoteSchema>;

type SourceType = "local" | "remote";

export default function AddDriverPage() {
  const navigate = useNavigate();
  const [sourceType, setSourceType] = useState<SourceType>("local");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const loadLocalMutation = useLoadLocalDriverMutation();
  const loadRemoteMutation = useLoadRemoteDriverMutation();
  const queryClient = useQueryClient();

  const localForm = useForm<LocalFormValues>({
    resolver: zodResolver(localSchema),
    defaultValues: { path: "" },
  });

  const remoteForm = useForm<RemoteFormValues>({
    resolver: zodResolver(remoteSchema),
    defaultValues: { repositoryUrl: "", branch: "main" },
  });

  const isSubmitting =
    localForm.formState.isSubmitting || remoteForm.formState.isSubmitting;

  const onSubmitLocal = async (values: LocalFormValues) => {
    setSubmitError(null);
    try {
      const data = await loadLocalMutation.mutateAsync({ path: values.path });
      queryClient.invalidateQueries({ queryKey: ["ListDrivers"] });
      if (data.loadLocalApplicationDriverVersion) {
        navigate({
          to: "/drivers/$driverId",
          params: {
            driverId:
              data.loadLocalApplicationDriverVersion.applicationDriverId,
          },
        });
      }
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Unknown error");
    }
  };

  const onSubmitRemote = async (values: RemoteFormValues) => {
    setSubmitError(null);
    try {
      const data = await loadRemoteMutation.mutateAsync({
        repositoryUrl: values.repositoryUrl,
        branch: values.branch,
      });
      queryClient.invalidateQueries({ queryKey: ["ListDrivers"] });
      if (data.loadRemoteApplicationDriverVersion) {
        navigate({
          to: "/drivers/$driverId",
          params: {
            driverId:
              data.loadRemoteApplicationDriverVersion.applicationDriverId,
          },
        });
      }
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Unknown error");
    }
  };

  return (
    <PageLayout
      title="Add Driver"
      breadcrumbs={[
        { label: "Drivers", href: "/drivers" },
        { label: "Add Driver" },
      ]}
    >
      <div className="max-w-lg mx-auto space-y-6">
        {submitError && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Failed to load driver</AlertTitle>
            <AlertDescription>{submitError}</AlertDescription>
          </Alert>
        )}

        <div className="flex gap-2">
          <Button
            variant={sourceType === "local" ? "default" : "outline"}
            onClick={() => setSourceType("local")}
          >
            Local
          </Button>
          <Button
            variant={sourceType === "remote" ? "default" : "outline"}
            onClick={() => setSourceType("remote")}
          >
            Remote
          </Button>
        </div>

        {sourceType === "local" ? (
          <form
            onSubmit={localForm.handleSubmit(onSubmitLocal)}
            className="space-y-4"
          >
            <div className="space-y-2">
              <Label htmlFor="path">Filesystem Path</Label>
              <Input
                id="path"
                placeholder="/path/to/driver"
                {...localForm.register("path")}
              />
              {localForm.formState.errors.path && (
                <p className="text-sm text-destructive">
                  {localForm.formState.errors.path.message}
                </p>
              )}
            </div>
            <div className="flex gap-2">
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? "Loading..." : "Load Driver"}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => navigate({ to: "/drivers" })}
              >
                Cancel
              </Button>
            </div>
          </form>
        ) : (
          <form
            onSubmit={remoteForm.handleSubmit(onSubmitRemote)}
            className="space-y-4"
          >
            <div className="space-y-2">
              <Label htmlFor="repositoryUrl">Repository URL</Label>
              <Input
                id="repositoryUrl"
                placeholder="https://github.com/org/repo"
                {...remoteForm.register("repositoryUrl")}
              />
              {remoteForm.formState.errors.repositoryUrl && (
                <p className="text-sm text-destructive">
                  {remoteForm.formState.errors.repositoryUrl.message}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="branch">Branch</Label>
              <Input
                id="branch"
                placeholder="main"
                {...remoteForm.register("branch")}
              />
              {remoteForm.formState.errors.branch && (
                <p className="text-sm text-destructive">
                  {remoteForm.formState.errors.branch.message}
                </p>
              )}
            </div>
            <div className="flex gap-2">
              <Button type="submit" disabled={isSubmitting}>
                {isSubmitting ? "Loading..." : "Load Driver"}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => navigate({ to: "/drivers" })}
              >
                Cancel
              </Button>
            </div>
          </form>
        )}
      </div>
    </PageLayout>
  );
}
