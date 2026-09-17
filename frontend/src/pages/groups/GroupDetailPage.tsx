import { useEffect, useMemo, useState, type FormEvent } from "react";
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
import { roleLabel } from "@/auth/roleLabel";
import { ConfirmDialog } from "@/components/ConfirmDialog";
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
import { useDocumentTitle } from "@/hooks/use-document-title";

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
  // current members we query the full user list (active + inactive) and filter
  // client-side. Loading inactive users too is required so the editor never
  // silently drops them from the group on save (see B1 in spec 011).
  const groupsQuery = useListGroupsQuery({ search: null });
  const usersQuery = useListUsersQuery({
    active: null,
    role: null,
    search: null,
  });

  const group: GroupRow | undefined = useMemo(
    () => groupsQuery.data?.groups.find((g) => g.id === id),
    [groupsQuery.data, id],
  );
  useDocumentTitle(group?.name ?? "Group");

  const allUsers = useMemo(
    () => usersQuery.data?.users ?? [],
    [usersQuery.data],
  );

  const activeUsers = useMemo(
    () => allUsers.filter((u) => u.active),
    [allUsers],
  );

  // Inactive users that are currently members of THIS group. Surfaced as a
  // read-only sub-section in the members editor so the admin can see (and
  // optionally remove) them, but cannot newly add an inactive user.
  const currentInactiveMembers = useMemo(
    () =>
      allUsers.filter((u) => !u.active && u.groups.some((g) => g.id === id)),
    [allUsers, id],
  );

  // Current members (full set, active + inactive) = users whose `.groups`
  // contains this group id. Used to seed the form and detect changes.
  const currentMemberIds = useMemo(
    () =>
      allUsers
        .filter((u) => u.groups.some((g) => g.id === id))
        .map((u) => u.id),
    [allUsers, id],
  );

  // Form state — seeded by effects keyed on the loaded entity. The name/role
  // half seeds from `group`; the memberIds half seeds from the derived
  // membership list (and waits for the users query to arrive). Splitting the
  // two effects mirrors the original guard pattern but keeps the setState
  // calls out of the render path.
  const [name, setName] = useState("");
  const [role, setRole] = useState<Role>("READ_ONLY");
  const [memberIds, setMemberIds] = useState<string[]>([]);

  useEffect(() => {
    if (group === undefined) return;
    setName(group.name);
    setRole(group.role);
    // Only reseed when we land on a different group; in-progress edits to
    // the same group must survive refetches.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [group?.id]);

  useEffect(() => {
    if (group === undefined || usersQuery.data === undefined) return;
    setMemberIds(currentMemberIds);
    // Reseed when the group id changes OR the users query first arrives.
    // currentMemberIds is recomputed by useMemo from those inputs, so we
    // drive the dependency array off the underlying data.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [group?.id, usersQuery.data !== undefined]);

  const [nameFieldError, setNameFieldError] = useState<string | null>(null);
  const [roleFieldError, setRoleFieldError] = useState<string | null>(null);
  const [membersFieldError, setMembersFieldError] = useState<string | null>(
    null,
  );
  const [deleteFieldError, setDeleteFieldError] = useState<string | null>(null);
  const [generalError, setGeneralError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);

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

  function requestDelete(): void {
    if (group === undefined) return;
    setDeleteFieldError(null);
    setGeneralError(null);
    setDeleteOpen(true);
  }

  function confirmDelete(): void {
    if (group === undefined) return;
    deleteGroupMutation.mutate(
      { id: group.id },
      {
        onSettled: () => setDeleteOpen(false),
      },
    );
  }

  function cancelDelete(): void {
    if (deleteGroupMutation.isPending) return;
    setDeleteOpen(false);
  }

  function toggleMember(userId: string, checked: boolean): void {
    setMemberIds((current) => {
      if (checked) {
        return current.includes(userId) ? current : [...current, userId];
      }
      return current.filter((u) => u !== userId);
    });
  }

  // Only block on the groups query — the users query feeds the member editor
  // and surfaces its own inline error/retry, so we render the page even when
  // it fails or is still loading (B2 in spec 011).
  if (groupsQuery.isLoading) {
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
  // Members data must be loaded before submission, otherwise we'd send an
  // empty memberIds replacement that wipes existing membership.
  const membersReady = usersQuery.data !== undefined;

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
              onClick={requestDelete}
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
              <Badge title={group.role}>{roleLabel(group.role)}</Badge>
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
                <SelectItem value="READ_ONLY">
                  {roleLabel("READ_ONLY")}
                </SelectItem>
                <SelectItem value="READ_WRITE">
                  {roleLabel("READ_WRITE")}
                </SelectItem>
                <SelectItem value="ADMIN">{roleLabel("ADMIN")}</SelectItem>
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

          <div className="space-y-4">
            <Label>Members</Label>
            {usersQuery.error ? (
              <div data-testid="group-members-error">
                <ErrorState
                  title="Failed to load users"
                  message={usersQuery.error.message}
                  onRetry={() => usersQuery.refetch()}
                />
              </div>
            ) : (
              <>
                <div className="space-y-2">
                  <p className="text-sm text-muted-foreground">
                    Active members
                  </p>
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
                </div>

                {currentInactiveMembers.length > 0 && (
                  <div className="space-y-2">
                    <p className="text-sm text-muted-foreground">
                      Inactive members
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Will remain in group. Uncheck to remove.
                    </p>
                    <div
                      className="space-y-2"
                      data-testid="group-inactive-members-list"
                    >
                      {currentInactiveMembers.map((u) => {
                        const checked = memberIds.includes(u.id);
                        return (
                          <div
                            key={u.id}
                            className="flex items-center gap-2"
                            data-user-id={u.id}
                            data-inactive="true"
                          >
                            <Checkbox
                              id={`group-inactive-member-${u.id}`}
                              checked={checked}
                              onCheckedChange={(value) =>
                                toggleMember(u.id, value === true)
                              }
                              disabled={submitting}
                            />
                            <Label htmlFor={`group-inactive-member-${u.id}`}>
                              {u.username}{" "}
                              <span className="text-xs text-muted-foreground">
                                ({u.displayName} — inactive)
                              </span>
                            </Label>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </>
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
              disabled={submitting || !membersReady}
              data-testid="group-edit-save"
            >
              <Save className="h-4 w-4 mr-1" />
              {submitting ? "Saving…" : "Save changes"}
            </Button>
          </div>
        </form>

        <ConfirmDialog
          open={deleteOpen}
          title="Delete group?"
          description={
            <>
              <p>
                This will permanently delete <strong>{group.name}</strong> and
                remove all of its memberships.
              </p>
              <p className="mt-2">This action cannot be undone.</p>
            </>
          }
          confirmLabel="Delete group"
          busy={deleteGroupMutation.isPending}
          onConfirm={confirmDelete}
          onCancel={cancelDelete}
          data-testid="group-delete-confirm"
        />
      </div>
    </PageLayout>
  );
}
