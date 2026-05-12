import { useMemo, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { AlertCircle, Save, Trash2 } from "lucide-react";

import {
  useListGroupsQuery,
  useListUsersQuery,
  useUpdateGroupMutation,
  useDeleteGroupMutation,
  type ListGroupsQuery,
  type Role,
} from "@/generated/graphql";
import { GraphQLOperationError } from "@/lib/graphql-fetcher";
import { PageLayout } from "@/components/PageLayout";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Checkbox } from "@/components/ui/checkbox";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type GroupRow = ListGroupsQuery["groups"][number];

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

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : "Unknown error";
}

export default function GroupDetailPage() {
  const { id } = useParams({ from: "/groups/$id" });
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  // Backend `type Group` exposes only {id, name, role}, no `members`. To show
  // current members we query active users and filter client-side. The same
  // query feeds the multi-select.
  const groupsQuery = useListGroupsQuery({ search: null });
  const usersQuery = useListUsersQuery({
    active: true,
    role: null,
    search: null,
  });

  const group: GroupRow | undefined = useMemo(
    () => groupsQuery.data?.groups.find((g) => g.id === id),
    [groupsQuery.data, id],
  );

  const activeUsers = useMemo(
    () => usersQuery.data?.users ?? [],
    [usersQuery.data],
  );

  // Current members = users whose `.groups` contains this group id.
  const currentMemberIds = useMemo(
    () =>
      activeUsers
        .filter((u) => u.groups.some((g) => g.id === id))
        .map((u) => u.id),
    [activeUsers, id],
  );

  // Form state — seed once per group id.
  const [seededId, setSeededId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("READ_ONLY");
  const [memberIds, setMemberIds] = useState<string[]>([]);

  // We seed name/role from the `group` and memberIds from the derived
  // membership list. Both data sources arrive independently, so seed each
  // half as soon as it's available; the per-half guard prevents oscillation.
  const [seededMembers, setSeededMembers] = useState<string | null>(null);

  if (group !== undefined && seededId !== group.id) {
    setSeededId(group.id);
    setName(group.name);
    setRole(group.role);
  }
  if (
    group !== undefined &&
    usersQuery.data !== undefined &&
    seededMembers !== group.id
  ) {
    setSeededMembers(group.id);
    setMemberIds(currentMemberIds);
  }

  const [nameFieldError, setNameFieldError] = useState<string | null>(null);
  const [roleFieldError, setRoleFieldError] = useState<string | null>(null);
  const [membersFieldError, setMembersFieldError] = useState<string | null>(
    null,
  );
  const [deleteFieldError, setDeleteFieldError] = useState<string | null>(null);
  const [generalError, setGeneralError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const updateGroupMutation = useUpdateGroupMutation({
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["ListGroups"] });
      void queryClient.invalidateQueries({ queryKey: ["ListUsers"] });
      setSuccessMessage("Group updated.");
      setNameFieldError(null);
      setRoleFieldError(null);
      setMembersFieldError(null);
      setGeneralError(null);
    },
    onError: (err) => {
      const code = extractCode(err);
      const msg = errorMessage(err);
      if (code === "DUPLICATE_GROUP_NAME") {
        setNameFieldError(msg);
      } else if (code === "LAST_ADMIN") {
        // LAST_ADMIN can come from a role demotion or a member removal — point
        // at whichever field changed.
        if (group !== undefined && role !== group.role) {
          setRoleFieldError(msg);
        } else {
          setMembersFieldError(msg);
        }
      } else {
        setGeneralError(msg);
      }
    },
  });

  const deleteGroupMutation = useDeleteGroupMutation({
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["ListGroups"] });
      void queryClient.invalidateQueries({ queryKey: ["ListUsers"] });
      void navigate({ to: "/groups" });
    },
    onError: (err) => {
      const code = extractCode(err);
      const msg = errorMessage(err);
      if (code === "LAST_ADMIN") {
        setDeleteFieldError(msg);
      } else {
        setGeneralError(msg);
      }
    },
  });

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (group === undefined) return;
    setSuccessMessage(null);
    setNameFieldError(null);
    setRoleFieldError(null);
    setMembersFieldError(null);
    setGeneralError(null);

    const currentSorted = [...currentMemberIds].sort();
    const nextSorted = [...memberIds].sort();
    const membersChanged =
      currentSorted.length !== nextSorted.length ||
      currentSorted.some((mid, i) => mid !== nextSorted[i]);

    updateGroupMutation.mutate({
      id: group.id,
      input: {
        name: name !== group.name ? name : null,
        role: role !== group.role ? role : null,
        memberIds: membersChanged ? memberIds : null,
      },
    });
  }

  function handleDelete(): void {
    if (group === undefined) return;
    setDeleteFieldError(null);
    setGeneralError(null);
    const ok = window.confirm(
      `Delete group "${group.name}"? This cannot be undone.`,
    );
    if (!ok) return;
    deleteGroupMutation.mutate({ id: group.id });
  }

  function toggleMember(userId: string, checked: boolean): void {
    setMemberIds((current) => {
      if (checked) {
        return current.includes(userId) ? current : [...current, userId];
      }
      return current.filter((u) => u !== userId);
    });
  }

  if (groupsQuery.isLoading || usersQuery.isLoading) {
    return (
      <PageLayout
        title="Group"
        breadcrumbs={[{ label: "Groups", href: "/groups" }, { label: "..." }]}
      >
        <LoadingState message="Loading group..." />
      </PageLayout>
    );
  }

  if (groupsQuery.error) {
    return (
      <PageLayout
        title="Group"
        breadcrumbs={[{ label: "Groups", href: "/groups" }, { label: "..." }]}
      >
        <ErrorState
          message={groupsQuery.error.message}
          onRetry={() => groupsQuery.refetch()}
        />
      </PageLayout>
    );
  }

  if (group === undefined) {
    return (
      <PageLayout
        title="Group not found"
        breadcrumbs={[{ label: "Groups", href: "/groups" }]}
      >
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Group not found</AlertTitle>
          <AlertDescription>
            No group exists with the supplied identifier.
          </AlertDescription>
        </Alert>
      </PageLayout>
    );
  }

  const submitting = updateGroupMutation.isPending;

  return (
    <PageLayout
      title={group.name}
      breadcrumbs={[
        { label: "Groups", href: "/groups" },
        { label: group.name },
      ]}
      actions={
        <div className="flex items-center gap-2">
          <div className="flex flex-col items-end">
            <Button
              size="sm"
              variant="destructive"
              onClick={handleDelete}
              disabled={deleteGroupMutation.isPending}
              data-testid="group-delete-button"
            >
              <Trash2 className="h-4 w-4 mr-1" />
              Delete
            </Button>
            {deleteFieldError && (
              <p
                className="mt-1 text-xs text-destructive"
                data-testid="group-delete-inline-error"
              >
                {deleteFieldError}
              </p>
            )}
          </div>
        </div>
      }
    >
      <div className="space-y-6">
        {generalError && (
          <Alert variant="destructive" data-testid="group-detail-error">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Error</AlertTitle>
            <AlertDescription>{generalError}</AlertDescription>
          </Alert>
        )}
        {successMessage && (
          <Alert data-testid="group-detail-success">
            <AlertTitle>Saved</AlertTitle>
            <AlertDescription>{successMessage}</AlertDescription>
          </Alert>
        )}

        <div className="rounded-md border bg-card p-4">
          <dl className="grid grid-cols-2 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Name</dt>
            <dd className="font-mono">{group.name}</dd>
            <dt className="text-muted-foreground">Role</dt>
            <dd>
              <Badge>{group.role}</Badge>
            </dd>
            <dt className="text-muted-foreground">Members</dt>
            <dd>{currentMemberIds.length}</dd>
          </dl>
        </div>

        <form
          onSubmit={handleSubmit}
          className="space-y-4 rounded-md border bg-card p-4"
          data-testid="group-edit-form"
        >
          <h2 className="text-lg font-semibold">Edit group</h2>

          <div className="space-y-2">
            <Label htmlFor="group-name">Name</Label>
            <Input
              id="group-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={submitting}
            />
            {nameFieldError && (
              <p
                className="text-sm text-destructive"
                data-testid="group-name-inline-error"
              >
                {nameFieldError}
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="group-role">Role</Label>
            <Select
              value={role}
              onValueChange={(value) => setRole(value as Role)}
              disabled={submitting}
            >
              <SelectTrigger id="group-role" data-testid="group-role-trigger">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="READ_ONLY">READ_ONLY</SelectItem>
                <SelectItem value="READ_WRITE">READ_WRITE</SelectItem>
                <SelectItem value="ADMIN">ADMIN</SelectItem>
              </SelectContent>
            </Select>
            {roleFieldError && (
              <p
                className="text-sm text-destructive"
                data-testid="group-role-inline-error"
              >
                {roleFieldError}
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label>Members</Label>
            {activeUsers.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No active users available.
              </p>
            ) : (
              <div
                className="space-y-2"
                data-testid="group-members-multiselect"
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
                        id={`group-member-${u.id}`}
                        checked={checked}
                        onCheckedChange={(value) =>
                          toggleMember(u.id, value === true)
                        }
                        disabled={submitting}
                      />
                      <Label htmlFor={`group-member-${u.id}`}>
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
            {membersFieldError && (
              <p
                className="text-sm text-destructive"
                data-testid="group-members-inline-error"
              >
                {membersFieldError}
              </p>
            )}
          </div>

          <div className="flex justify-end">
            <Button
              type="submit"
              disabled={submitting}
              data-testid="group-edit-save"
            >
              <Save className="h-4 w-4 mr-1" />
              {submitting ? "Saving…" : "Save changes"}
            </Button>
          </div>
        </form>
      </div>
    </PageLayout>
  );
}
