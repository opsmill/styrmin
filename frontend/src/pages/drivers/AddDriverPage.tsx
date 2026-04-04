import { useNavigate } from "@tanstack/react-router";
import { useForm, useStore } from "@tanstack/react-form";
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

type SourceType = "local" | "remote";

export default function AddDriverPage() {
  const navigate = useNavigate();
  const [sourceType, setSourceType] = useState<SourceType>("local");
  const [submitError, setSubmitError] = useState<string | null>(null);
  const loadLocalMutation = useLoadLocalDriverMutation();
  const loadRemoteMutation = useLoadRemoteDriverMutation();
  const queryClient = useQueryClient();

  const localForm = useForm({
    defaultValues: { path: "" },
    validators: {
      onSubmit: localSchema,
    },
    onSubmit: async ({ value }) => {
      setSubmitError(null);
      try {
        const data = await loadLocalMutation.mutateAsync({
          path: value.path,
        });
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
    },
  });

  const remoteForm = useForm({
    defaultValues: { repositoryUrl: "", branch: "main" },
    validators: {
      onSubmit: remoteSchema,
    },
    onSubmit: async ({ value }) => {
      setSubmitError(null);
      try {
        const data = await loadRemoteMutation.mutateAsync({
          repositoryUrl: value.repositoryUrl,
          branch: value.branch,
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
    },
  });

  const localSubmitting = useStore(localForm.store, (s) => s.isSubmitting);
  const remoteSubmitting = useStore(remoteForm.store, (s) => s.isSubmitting);
  const isSubmitting = localSubmitting || remoteSubmitting;

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
            onSubmit={(e) => {
              e.preventDefault();
              e.stopPropagation();
              localForm.handleSubmit();
            }}
            className="space-y-4"
          >
            <localForm.Field name="path">
              {(field) => (
                <div className="space-y-2">
                  <Label htmlFor="path">Filesystem Path</Label>
                  <Input
                    id="path"
                    placeholder="/path/to/driver"
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
            </localForm.Field>
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
            onSubmit={(e) => {
              e.preventDefault();
              e.stopPropagation();
              remoteForm.handleSubmit();
            }}
            className="space-y-4"
          >
            <remoteForm.Field name="repositoryUrl">
              {(field) => (
                <div className="space-y-2">
                  <Label htmlFor="repositoryUrl">Repository URL</Label>
                  <Input
                    id="repositoryUrl"
                    placeholder="https://github.com/org/repo"
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
            </remoteForm.Field>
            <remoteForm.Field name="branch">
              {(field) => (
                <div className="space-y-2">
                  <Label htmlFor="branch">Branch</Label>
                  <Input
                    id="branch"
                    placeholder="main"
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
            </remoteForm.Field>
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
