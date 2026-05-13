import { useState, type FormEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Plus, AlertCircle } from "lucide-react";

import {
  useCreateGroupMutation,
  useListUsersQuery,
  type Role,
} from "@/generated/graphql";
import { GraphQLOperationError } from "@/lib/graphql-fetcher";
import { roleLabel } from "@/auth/roleLabel";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

interface CreateGroupDialogProps {
  onCreated?: () => void;
}

interface CodeError extends Error {
  code?: string;
}

function extractCode(err: unknown): string | null {
  if (err instanceof GraphQLOperationError) {
    return err.code;
  }
  if (err instanceof Error) {
    const code = (err as CodeError).code;
    return typeof code === "string" ? code : null;
  }
  return null;
}

export function CreateGroupDialog({ onCreated }: CreateGroupDialogProps) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("READ_ONLY");
  const [memberIds, setMemberIds] = useState<string[]>([]);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [nameFieldError, setNameFieldError] = useState<string | null>(null);

  // Member multi-select: only show active users (admin can't add inactive users).
  const usersQuery = useListUsersQuery({
    active: true,
    role: null,
    search: null,
  });
  const activeUsers = usersQuery.data?.users ?? [];

  const queryClient = useQueryClient();
  const createGroupMutation = useCreateGroupMutation({
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["ListGroups"] });
      void queryClient.invalidateQueries({ queryKey: ["ListUsers"] });
      setName("");
      setRole("READ_ONLY");
      setMemberIds([]);
      setSubmitError(null);
      setNameFieldError(null);
      setOpen(false);
      onCreated?.();
    },
    onError: (err) => {
      const code = extractCode(err);
      const msg = err instanceof Error ? err.message : "Unknown error";
      if (code === "DUPLICATE_GROUP_NAME") {
        setNameFieldError(msg);
      } else {
        setSubmitError(msg);
      }
    },
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    event.stopPropagation();
    if (createGroupMutation.isPending) return;
    setSubmitError(null);
    setNameFieldError(null);
    createGroupMutation.mutate({
      input: {
        name,
        role,
        memberIds: memberIds.length === 0 ? null : memberIds,
      },
    });
  }

  function handleOpenChange(nextOpen: boolean): void {
    setOpen(nextOpen);
    if (!nextOpen) {
      setName("");
      setRole("READ_ONLY");
      setMemberIds([]);
      setSubmitError(null);
      setNameFieldError(null);
    }
  }

  function toggleMember(userId: string, checked: boolean): void {
    setMemberIds((current) => {
      if (checked) {
        return current.includes(userId) ? current : [...current, userId];
      }
      return current.filter((u) => u !== userId);
    });
  }

  const submitting = createGroupMutation.isPending;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button size="sm" data-testid="groups-create-button">
          <Plus className="h-4 w-4 mr-1" />
          Create group
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Create group</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          {submitError && (
            <Alert variant="destructive" data-testid="create-group-error">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Error</AlertTitle>
              <AlertDescription>{submitError}</AlertDescription>
            </Alert>
          )}

          <div className="space-y-2">
            <Label htmlFor="create-group-name">Name</Label>
            <Input
              id="create-group-name"
              value={name}
              required
              onChange={(e) => setName(e.target.value)}
              disabled={submitting}
            />
            {nameFieldError && (
              <p
                className="text-sm text-destructive"
                data-testid="create-group-name-inline-error"
              >
                {nameFieldError}
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="create-group-role">Role</Label>
            <Select
              value={role}
              onValueChange={(value) => setRole(value as Role)}
            >
              <SelectTrigger id="create-group-role">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="READ_ONLY">{roleLabel("READ_ONLY")}</SelectItem>
                <SelectItem value="READ_WRITE">{roleLabel("READ_WRITE")}</SelectItem>
                <SelectItem value="ADMIN">{roleLabel("ADMIN")}</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-2">
            <Label>Initial members</Label>
            {activeUsers.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No active users available.
              </p>
            ) : (
              <div
                className="space-y-2"
                data-testid="create-group-members-multiselect"
              >
                {activeUsers.map((u) => {
                  const checked = memberIds.includes(u.id);
                  return (
                    <div
                      key={u.id}
                      className="flex items-center gap-2"
                      data-user-id={u.id}
                    >
                      <Checkbox
                        id={`create-group-member-${u.id}`}
                        checked={checked}
                        onCheckedChange={(value) =>
                          toggleMember(u.id, value === true)
                        }
                        disabled={submitting}
                      />
                      <Label htmlFor={`create-group-member-${u.id}`}>
                        {u.username}{" "}
                        <span className="text-xs text-muted-foreground">
                          ({u.displayName})
                        </span>
                      </Label>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => handleOpenChange(false)}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? "Creating…" : "Create"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
