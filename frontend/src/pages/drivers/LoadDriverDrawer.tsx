import { useEffect, useState } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { useNavigate } from "@tanstack/react-router";
import { useForm, useStore } from "@tanstack/react-form";
import { useQueryClient } from "@tanstack/react-query";
import { z } from "zod/v4";
import { X } from "lucide-react";
import {
  useLoadLocalDriverMutation,
  useLoadRemoteDriverMutation,
} from "@/generated/graphql";
import { Tabs } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertCircle } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { cn } from "@/lib/utils";
import { fieldError } from "@/lib/field-error";

const localSchema = z.object({
  path: z.string().min(1, "Path is required"),
});

const remoteSchema = z.object({
  repositoryUrl: z.string().min(1, "Repository URL is required"),
  branch: z.string().min(1, "Branch is required"),
});

type SourceTab = "git" | "local";

const FORM_ID = "load-driver-form";

interface LoadDriverDrawerProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Right-side slide-in drawer for loading a driver from a Git repository or a
 * local directory. Follows the app's drawer pattern (see ConfigEditDrawer);
 * the centered-dialog pattern is reserved for shorter create/confirm flows.
 *
 * One-shot load: the backend has no scan/preview step, so submitting calls the
 * load mutation directly. On success the drawer closes, a success toast
 * confirms which version was loaded (or a warning toast lists the `spec.info`
 * values the load left out), and we navigate to the new version's detail page.
 */
export function LoadDriverDrawer({
  open,
  onOpenChange,
}: LoadDriverDrawerProps) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [tab, setTab] = useState<SourceTab>("git");
  const [submitError, setSubmitError] = useState<string | null>(null);

  const loadLocalMutation = useLoadLocalDriverMutation();
  const loadRemoteMutation = useLoadRemoteDriverMutation();

  const handleLoaded = (v: {
    applicationDriverId: string;
    id: string;
    version: string;
    loadWarnings?: readonly string[];
  }) => {
    queryClient.invalidateQueries({ queryKey: ["ListDrivers"] });
    onOpenChange(false);
    const selectable = `Version ${v.version} is now selectable when deploying or upgrading.`;
    const warnings = v.loadWarnings ?? [];
    if (warnings.length > 0) {
      // Kept on screen until dismissed: the warnings are not stored anywhere.
      toast.add({
        title: "Driver loaded with warnings",
        description: [selectable, ...warnings.map((w) => `• ${w}`)].join("\n"),
        type: "warning",
        timeout: 0,
      });
    } else {
      toast.add({
        title: "Driver loaded",
        description: selectable,
        type: "success",
      });
    }
    navigate({
      to: "/drivers/$driverId",
      params: { driverId: v.applicationDriverId },
      search: { version: v.id },
    });
  };

  const remoteForm = useForm({
    defaultValues: { repositoryUrl: "", branch: "main" },
    validators: { onSubmit: remoteSchema },
    onSubmit: async ({ value }) => {
      setSubmitError(null);
      try {
        const data = await loadRemoteMutation.mutateAsync(value);
        const v = data.loadRemoteApplicationDriverVersion;
        if (v) handleLoaded(v);
      } catch (err) {
        setSubmitError(err instanceof Error ? err.message : "Unknown error");
      }
    },
  });

  const localForm = useForm({
    defaultValues: { path: "" },
    validators: { onSubmit: localSchema },
    onSubmit: async ({ value }) => {
      setSubmitError(null);
      try {
        const data = await loadLocalMutation.mutateAsync(value);
        const v = data.loadLocalApplicationDriverVersion;
        if (v) handleLoaded(v);
      } catch (err) {
        setSubmitError(err instanceof Error ? err.message : "Unknown error");
      }
    },
  });

  const remoteSubmitting = useStore(remoteForm.store, (s) => s.isSubmitting);
  const localSubmitting = useStore(localForm.store, (s) => s.isSubmitting);
  const isSubmitting = remoteSubmitting || localSubmitting;

  useEffect(() => {
    if (open) {
      setTab("git");
      setSubmitError(null);
      remoteForm.reset();
      localForm.reset();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const submitActiveForm = () => {
    if (tab === "git") remoteForm.handleSubmit();
    else localForm.handleSubmit();
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Backdrop
          className={cn(
            "fixed inset-0 z-40 bg-black/55 opacity-100 transition-opacity duration-200 ease-out",
            "data-[starting-style]:opacity-0 data-[ending-style]:opacity-0",
          )}
        />
        <Dialog.Popup
          aria-labelledby="load-driver-title"
          className={cn(
            "fixed right-0 top-0 z-50 flex h-screen flex-col bg-background text-foreground shadow-2xl outline-none",
            "w-full sm:w-[540px]",
            "translate-x-0 transition-transform duration-200 ease-out",
            "data-[starting-style]:translate-x-full data-[ending-style]:translate-x-full",
          )}
        >
          <header className="flex shrink-0 items-start justify-between gap-4 border-b border-border px-7 py-5">
            <div className="flex min-w-0 flex-col gap-1.5">
              <span className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
                Load driver
              </span>
              <Dialog.Title
                id="load-driver-title"
                className="text-base font-semibold text-foreground"
              >
                Load a driver
              </Dialog.Title>
              <Dialog.Description className="text-sm text-muted-foreground">
                From a Git repository or a local directory. It becomes
                selectable when deploying or upgrading its application.
              </Dialog.Description>
            </div>
            <Dialog.Close
              render={
                <button
                  type="button"
                  aria-label="Close"
                  className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              }
            >
              <X className="h-4 w-4" />
            </Dialog.Close>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto px-7 py-6">
            <Tabs
              tabs={[
                { id: "git", label: "Git repository" },
                { id: "local", label: "Local directory" },
              ]}
              activeTab={tab}
              onTabChange={(id) => {
                setTab(id as SourceTab);
                setSubmitError(null);
              }}
            />

            {submitError && (
              <Alert variant="destructive" className="mt-4">
                <AlertCircle className="h-4 w-4" />
                <AlertTitle>Couldn't load the driver</AlertTitle>
                <AlertDescription className="whitespace-pre-line">
                  {submitError}
                </AlertDescription>
              </Alert>
            )}

            <form
              id={FORM_ID}
              onSubmit={(e) => {
                e.preventDefault();
                e.stopPropagation();
                submitActiveForm();
              }}
              className="mt-6 space-y-5"
            >
              {tab === "git" ? (
                <>
                  <remoteForm.Field name="repositoryUrl">
                    {(field) => (
                      <div className="space-y-2">
                        <Label htmlFor="repositoryUrl">Repository URL</Label>
                        <Input
                          id="repositoryUrl"
                          placeholder="https://github.com/org/repo"
                          className="font-mono text-xs"
                          value={field.state.value}
                          onChange={(e) => field.handleChange(e.target.value)}
                          onBlur={field.handleBlur}
                        />
                        {field.state.meta.errors.length > 0 && (
                          <p className="text-sm text-destructive">
                            {fieldError(field.state.meta.errors[0])}
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
                          className="font-mono text-xs"
                          value={field.state.value}
                          onChange={(e) => field.handleChange(e.target.value)}
                          onBlur={field.handleBlur}
                        />
                        {field.state.meta.errors.length > 0 && (
                          <p className="text-sm text-destructive">
                            {fieldError(field.state.meta.errors[0])}
                          </p>
                        )}
                      </div>
                    )}
                  </remoteForm.Field>
                </>
              ) : (
                <localForm.Field name="path">
                  {(field) => (
                    <div className="space-y-2">
                      <Label htmlFor="path">Directory path</Label>
                      <Input
                        id="path"
                        placeholder="/path/to/driver"
                        className="font-mono text-xs"
                        value={field.state.value}
                        onChange={(e) => field.handleChange(e.target.value)}
                        onBlur={field.handleBlur}
                      />
                      {field.state.meta.errors.length > 0 && (
                        <p className="text-sm text-destructive">
                          {fieldError(field.state.meta.errors[0])}
                        </p>
                      )}
                      <p className="text-xs text-muted-foreground">
                        Path inside the Styrmin server container (a bundled or
                        mounted driver) — not your local machine.
                      </p>
                    </div>
                  )}
                </localForm.Field>
              )}
            </form>
          </div>

          <footer className="sticky bottom-0 z-10 flex items-center gap-3 border-t border-border bg-background px-7 py-4">
            <Button
              type="button"
              variant="outline"
              className="flex-1"
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              form={FORM_ID}
              className="flex-1"
              disabled={isSubmitting}
            >
              {isSubmitting ? "Loading..." : "Load driver"}
            </Button>
          </footer>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
