import { useRef, useState } from "react";
import { useForm } from "@tanstack/react-form";
import { AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { GraphQLOperationError } from "@/lib/graphql-fetcher";

// The same limits the server applies to a backup's name and description.
const BACKUP_NAME_MAX_LENGTH = 255;
const BACKUP_DESCRIPTION_MAX_LENGTH = 2000;

/** The fields to send. A field left out is not changed (edit) or defaulted (create). */
export interface BackupDetailsChanges {
  name?: string;
  description?: string;
}

interface BackupDetailsDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mode: "create" | "edit";
  initialName?: string;
  initialDescription?: string | null;
  /** Runs the mutation. A thrown error is shown in the dialog. */
  onSubmit: (changes: BackupDetailsChanges) => Promise<void>;
}

// Show the description's character count when it is this close to the limit.
const COUNTER_THRESHOLD = BACKUP_DESCRIPTION_MAX_LENGTH - 200;

// The server counts code points of the trimmed value, as Python's len() does.
const codePoints = (value: string) => [...value.trim()].length;

// Unicode category Cc, which the server rejects in a name.
// eslint-disable-next-line no-control-regex
const CONTROL_CHARACTER = /[\u0000-\u001f\u007f-\u009f]/;
// The same, without tab, line feed and carriage return, which a description allows.
const DESCRIPTION_CONTROL_CHARACTER =
  // eslint-disable-next-line no-control-regex
  /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]/;

function nameError(value: string, mode: "create" | "edit"): string | undefined {
  if (codePoints(value) > BACKUP_NAME_MAX_LENGTH)
    return `The name can have at most ${BACKUP_NAME_MAX_LENGTH} characters`;
  if (CONTROL_CHARACTER.test(value))
    return "The name cannot contain line breaks, tabs or other control characters";
  // In create mode an empty name means "use the default name".
  if (mode === "edit" && value.trim() === "") return "The name cannot be empty";
  return undefined;
}

function descriptionError(value: string): string | undefined {
  if (codePoints(value) > BACKUP_DESCRIPTION_MAX_LENGTH)
    return `The description can have at most ${BACKUP_DESCRIPTION_MAX_LENGTH.toLocaleString("en-US")} characters`;
  if (DESCRIPTION_CONTROL_CHARACTER.test(value))
    return "The description cannot contain control characters other than line breaks and tabs";
  return undefined;
}

/** The fields to send: the changed ones in edit mode, the filled ones in create mode. */
function backupDetailsChanges(
  mode: "create" | "edit",
  initial: { name: string; description: string },
  value: { name: string; description: string },
): BackupDetailsChanges {
  const name = value.name.trim();
  const changes: BackupDetailsChanges = {};
  if (mode === "create") {
    if (name) changes.name = name;
    if (value.description) changes.description = value.description;
  } else {
    if (name !== initial.name) changes.name = name;
    // An empty description clears it on the server.
    if (value.description !== initial.description)
      changes.description = value.description;
  }
  return changes;
}

function BackupDetailsForm({
  mode,
  initialName,
  initialDescription,
  onSubmit,
  onClose,
}: Omit<BackupDetailsDialogProps, "open" | "onOpenChange"> & {
  onClose: () => void;
}) {
  const [initial] = useState(() => ({
    name: initialName ?? "",
    description: initialDescription ?? "",
  }));
  const [error, setError] = useState<{ title: string; message: string } | null>(
    null,
  );

  const form = useForm({
    defaultValues: initial,
    onSubmit: async ({ value }) => {
      setError(null);
      const changes = backupDetailsChanges(mode, initial, value);
      if (mode === "edit" && Object.keys(changes).length === 0) {
        onClose();
        return;
      }
      try {
        await onSubmit(changes);
        onClose();
      } catch (err) {
        setError({
          title:
            err instanceof GraphQLOperationError &&
            err.code === "ALREADY_EXISTS"
              ? "Name already in use"
              : "Error",
          message: err instanceof Error ? err.message : "Unknown error",
        });
      }
    },
  });

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        e.stopPropagation();
        form.handleSubmit();
      }}
      className="space-y-4"
    >
      <form.Field
        name="name"
        validators={{ onChange: ({ value }) => nameError(value, mode) }}
      >
        {(field) => (
          <div className="flex flex-col gap-2">
            <Label htmlFor="backup-details-name">
              Name{mode === "create" ? " (optional)" : ""}
            </Label>
            <Input
              id="backup-details-name"
              data-testid="backup-details-name"
              value={field.state.value}
              placeholder={
                mode === "create"
                  ? "Leave empty to use styrmin-<backup id>"
                  : ""
              }
              onChange={(e) => field.handleChange(e.target.value)}
              onBlur={field.handleBlur}
              aria-invalid={field.state.meta.errors.length > 0}
              aria-describedby={
                field.state.meta.errors.length > 0
                  ? "backup-details-name-error"
                  : undefined
              }
            />
            {field.state.meta.errors.length > 0 && (
              <p
                id="backup-details-name-error"
                className="text-xs text-destructive"
                role="alert"
              >
                {String(field.state.meta.errors[0])}
              </p>
            )}
          </div>
        )}
      </form.Field>

      <form.Field
        name="description"
        validators={{ onChange: ({ value }) => descriptionError(value) }}
      >
        {(field) => {
          const hasError = field.state.meta.errors.length > 0;
          const count = codePoints(field.state.value);
          const showCounter = count >= COUNTER_THRESHOLD;
          const describedBy =
            [
              hasError && "backup-details-description-error",
              showCounter && "backup-details-description-counter",
            ]
              .filter(Boolean)
              .join(" ") || undefined;
          return (
            <div className="flex flex-col gap-2">
              <Label htmlFor="backup-details-description">
                Description (optional)
              </Label>
              <textarea
                id="backup-details-description"
                data-testid="backup-details-description"
                rows={4}
                className="w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                value={field.state.value}
                onChange={(e) => field.handleChange(e.target.value)}
                onBlur={field.handleBlur}
                aria-invalid={hasError}
                aria-describedby={describedBy}
              />
              {showCounter && (
                <p
                  id="backup-details-description-counter"
                  data-testid="backup-details-description-counter"
                  className={`text-xs ${count > BACKUP_DESCRIPTION_MAX_LENGTH ? "text-destructive" : "text-muted-foreground"}`}
                >
                  {count.toLocaleString("en-US")} /{" "}
                  {BACKUP_DESCRIPTION_MAX_LENGTH.toLocaleString("en-US")}
                </p>
              )}
              {hasError && (
                <p
                  id="backup-details-description-error"
                  className="text-xs text-destructive"
                  role="alert"
                >
                  {String(field.state.meta.errors[0])}
                </p>
              )}
            </div>
          );
        }}
      </form.Field>

      {error && (
        <Alert variant="destructive" data-testid="backup-details-error">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>{error.title}</AlertTitle>
          <AlertDescription>{error.message}</AlertDescription>
        </Alert>
      )}

      <form.Subscribe selector={(s) => [s.canSubmit, s.isSubmitting] as const}>
        {([canSubmit, isSubmitting]) => (
          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={onClose}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button
              type="submit"
              data-testid="backup-details-submit"
              data-autofocus={mode === "create" ? "" : undefined}
              disabled={!canSubmit || isSubmitting}
            >
              {mode === "create"
                ? isSubmitting
                  ? "Creating..."
                  : "Create backup"
                : isSubmitting
                  ? "Saving..."
                  : "Save"}
            </Button>
          </div>
        )}
      </form.Subscribe>
    </form>
  );
}

/**
 * Name and describe a backup: when it is created (`mode="create"`) or later
 * (`mode="edit"`). In create mode the submit button has focus, so Enter in the
 * empty dialog creates a backup with the default name.
 */
export function BackupDetailsDialog({
  open,
  onOpenChange,
  ...formProps
}: BackupDetailsDialogProps) {
  const popupRef = useRef<HTMLDivElement>(null);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        ref={popupRef}
        data-testid="backup-details-dialog"
        initialFocus={() =>
          formProps.mode === "create"
            ? popupRef.current?.querySelector<HTMLElement>("[data-autofocus]")
            : true
        }
      >
        <DialogHeader>
          <DialogTitle>
            {formProps.mode === "create" ? "Create Backup" : "Edit Backup"}
          </DialogTitle>
          <DialogDescription>
            {formProps.mode === "create"
              ? "Give the backup a name and a description, or leave them empty."
              : "Change the backup's name or description. The backup data does not change."}
          </DialogDescription>
        </DialogHeader>
        {open && (
          <BackupDetailsForm
            {...formProps}
            onClose={() => onOpenChange(false)}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
