import { useEffect, useMemo, useState, type FormEvent } from "react";
import { useNavigate, useParams } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { AlertCircle, KeyRound, Save, Trash2 } from "lucide-react";

import {
  useListUsersQuery,
  useListGroupsQuery,
  useUpdateUserMutation,
  useResetUserPasswordMutation,
  useDeleteUserMutation,
  type ListUsersQuery,
  type ListGroupsQuery,
  type Role,
} from "@/generated/graphql";
import { GraphQLOperationError } from "@/lib/graphql-fetcher";
import { roleLabel } from "@/auth/roleLabel";
import { PASSWORD_REQUIREMENTS_SUMMARY } from "@/auth/password-policy";
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
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useDocumentTitle } from "@/hooks/use-document-title";

type UserRow = ListUsersQuery["users"][number];
type GroupSummary = ListGroupsQuery["groups"][number];

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

export default function UserDetailPage() {
  const { id } = useParams({ from: "/users/$id" });
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const usersQuery = useListUsersQuery({
    active: null,
    role: null,
    search: null,
  });
  const groupsQuery = useListGroupsQuery({ search: null });

  const user: UserRow | undefined = useMemo(
    () => usersQuery.data?.users.find((u) => u.id === id),
    [usersQuery.data, id],
  );
  useDocumentTitle(user?.username ?? "User");

  const allGroups: GroupSummary[] = useMemo(
    () =>
      [...(groupsQuery.data?.groups ?? [])].sort((a, b) =>
        a.name.localeCompare(b.name),
      ),
    [groupsQuery.data],
  );

  // Form state — initialised from `user` once available. Reseeding is driven
  // by an effect keyed on the loaded user id so we don't violate React's
  // "no setState during render" rule. We deliberately only reseed when the
  // id changes (route change to a different user); seeding from the upstream
  // record on every refetch would discard in-progress edits.
  const [displayName, setDisplayName] = useState("");
  const [role, setRole] = useState<Role>("READ_ONLY");
  const [active, setActive] = useState(true);
  const [groupIds, setGroupIds] = useState<string[]>([]);

  // Keep a ref-style mirror of the *initial* user record so the effect can
  // seed once per id without re-running on every parent re-render. Using
  // `user?.id` as the sole dependency triggers a reseed only on identity
  // change; the seed-time values are pulled fresh from the closure.
  useEffect(() => {
    if (user === undefined) return;
    setDisplayName(user.displayName);
    setRole(user.role);
    setActive(user.active);
    setGroupIds(user.groups.map((g) => g.id));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);

  // Inline server-error state keyed to the affected control.
  const [roleFieldError, setRoleFieldError] = useState<string | null>(null);
  const [activeFieldError, setActiveFieldError] = useState<string | null>(null);
  const [groupsFieldError, setGroupsFieldError] = useState<string | null>(null);
  const [deleteFieldError, setDeleteFieldError] = useState<string | null>(null);
  const [generalError, setGeneralError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);

  const updateUserMutation = useUpdateUserMutation({
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["ListUsers"] });
      setSuccessMessage("User updated.");
      setRoleFieldError(null);
      setActiveFieldError(null);
      setGroupsFieldError(null);
      setGeneralError(null);
    },
    onError: (err, variables) => {
      const code = extractCode(err);
      const msg = errorMessage(err);
      if (code === "LAST_ADMIN") {
        // Surface the error on the control that caused the violation. Prefer
        // the mutation payload as the source of truth — `groupIds` set means
        // a membership change triggered the LAST_ADMIN guard (B4 in spec 011);
        // otherwise fall back to active/role checks against current state.
        const input = variables.input;
        if (input.groupIds !== null && input.groupIds !== undefined) {
          setGroupsFieldError(msg);
        } else if (user !== undefined && active !== user.active) {
          setActiveFieldError(msg);
        } else if (user !== undefined && role !== user.role) {
          setRoleFieldError(msg);
        } else {
          setGeneralError(msg);
        }
      } else {
        setGeneralError(msg);
      }
    },
  });

  const resetPasswordMutation = useResetUserPasswordMutation({
    onSuccess: () => {
      setSuccessMessage("Password reset. Existing sessions invalidated.");
    },
    onError: (err) => {
      setGeneralError(errorMessage(err));
    },
  });

  const deleteUserMutation = useDeleteUserMutation({
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["ListUsers"] });
      void navigate({ to: "/users" });
    },
    onError: (err) => {
      const code = extractCode(err);
      const msg = errorMessage(err);
      if (code === "USER_HAS_REFERENCES" || code === "LAST_ADMIN") {
        setDeleteFieldError(msg);
      } else {
        setGeneralError(msg);
      }
    },
  });

  // Reset-password dialog state.
  const [resetOpen, setResetOpen] = useState(false);
  const [newPassword, setNewPassword] = useState("");
  const [resetError, setResetError] = useState<string | null>(null);

  // Delete-confirm dialog state.
  const [deleteOpen, setDeleteOpen] = useState(false);

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (user === undefined) return;
    setSuccessMessage(null);
    setRoleFieldError(null);
    setActiveFieldError(null);
    setGroupsFieldError(null);
    setGeneralError(null);

    const currentGroupIds = user.groups.map((g) => g.id).sort();
    const nextGroupIds = [...groupIds].sort();
    const groupsChanged =
      currentGroupIds.length !== nextGroupIds.length ||
      currentGroupIds.some((gid, i) => gid !== nextGroupIds[i]);

    updateUserMutation.mutate({
      id: user.id,
      input: {
        displayName: displayName !== user.displayName ? displayName : null,
        role: role !== user.role ? role : null,
        active: active !== user.active ? active : null,
        groupIds: groupsChanged ? groupIds : null,
      },
    });
  }

  function handleResetPasswordSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (user === undefined) return;
    if (newPassword.length === 0) {
      setResetError("Password is required.");
      return;
    }
    setResetError(null);
    resetPasswordMutation.mutate(
      { userId: user.id, newPassword },
      {
        onSuccess: () => {
          setNewPassword("");
          setResetOpen(false);
        },
        onError: (err) => {
          setResetError(errorMessage(err));
        },
      },
    );
  }

  function requestDelete(): void {
    if (user === undefined) return;
    setDeleteFieldError(null);
    setGeneralError(null);
    setDeleteOpen(true);
  }

  function confirmDelete(): void {
    if (user === undefined) return;
    deleteUserMutation.mutate(
      { id: user.id },
      {
        onSettled: () => setDeleteOpen(false),
      },
    );
  }

  function cancelDelete(): void {
    if (deleteUserMutation.isPending) return;
    setDeleteOpen(false);
  }

  function toggleGroup(groupId: string, checked: boolean): void {
    setGroupIds((current) => {
      if (checked) {
        return current.includes(groupId) ? current : [...current, groupId];
      }
      return current.filter((g) => g !== groupId);
    });
  }

  if (usersQuery.isLoading) {
    return (
      <PageLayout
        title="User"
        breadcrumbs={[{ label: "Users", href: "/users" }, { label: "..." }]}
      >
        <LoadingState message="Loading user..." />
      </PageLayout>
    );
  }

  if (usersQuery.error) {
    return (
      <PageLayout
        title="User"
        breadcrumbs={[{ label: "Users", href: "/users" }, { label: "..." }]}
      >
        <ErrorState
          message={usersQuery.error.message}
          onRetry={() => usersQuery.refetch()}
        />
      </PageLayout>
    );
  }

  if (user === undefined) {
    return (
      <PageLayout
        title="User not found"
        breadcrumbs={[{ label: "Users", href: "/users" }]}
      >
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>User not found</AlertTitle>
          <AlertDescription>
            No user exists with the supplied identifier.
          </AlertDescription>
        </Alert>
      </PageLayout>
    );
  }

  const submitting = updateUserMutation.isPending;

  return (
    <PageLayout
      title={user.username}
      breadcrumbs={[
        { label: "Users", href: "/users" },
        { label: user.username },
      ]}
      actions={
        <div className="flex items-center gap-2">
          <Dialog open={resetOpen} onOpenChange={setResetOpen}>
            <DialogTrigger asChild>
              <Button
                size="sm"
                variant="outline"
                data-testid="user-reset-password-trigger"
              >
                <KeyRound className="h-4 w-4 mr-1" />
                Reset password
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Reset password</DialogTitle>
              </DialogHeader>
              <form onSubmit={handleResetPasswordSubmit} className="space-y-4">
                {resetError && (
                  <Alert variant="destructive">
                    <AlertCircle className="h-4 w-4" />
                    <AlertTitle>Error</AlertTitle>
                    <AlertDescription>{resetError}</AlertDescription>
                  </Alert>
                )}
                <p className="text-sm text-muted-foreground">
                  Set a new password for <strong>{user.username}</strong>. All
                  existing sessions for this user will be invalidated.
                </p>
                <div className="space-y-2">
                  <Label htmlFor="reset-password-new">New password</Label>
                  <Input
                    id="reset-password-new"
                    type="password"
                    autoComplete="new-password"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    required
                    aria-describedby="reset-password-policy"
                  />
                  <p
                    id="reset-password-policy"
                    className="text-xs text-muted-foreground"
                    data-testid="reset-password-policy"
                  >
                    {PASSWORD_REQUIREMENTS_SUMMARY}
                  </p>
                </div>
                <div className="flex justify-end gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setResetOpen(false)}
                  >
                    Cancel
                  </Button>
                  <Button
                    type="submit"
                    disabled={resetPasswordMutation.isPending}
                  >
                    {resetPasswordMutation.isPending ? "Resetting…" : "Reset"}
                  </Button>
                </div>
              </form>
            </DialogContent>
          </Dialog>

          <div className="flex flex-col items-end">
            <Button
              size="sm"
              variant="destructive"
              onClick={requestDelete}
              disabled={deleteUserMutation.isPending}
              data-testid="user-delete-button"
            >
              <Trash2 className="h-4 w-4 mr-1" />
              Delete
            </Button>
            {deleteFieldError && (
              <p
                className="mt-1 text-xs text-destructive"
                data-testid="user-delete-inline-error"
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
          <Alert variant="destructive" data-testid="user-detail-error">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Error</AlertTitle>
            <AlertDescription>{generalError}</AlertDescription>
          </Alert>
        )}
        {successMessage && (
          <Alert data-testid="user-detail-success">
            <AlertTitle>Saved</AlertTitle>
            <AlertDescription>{successMessage}</AlertDescription>
          </Alert>
        )}

        <div className="rounded-md border bg-card p-4">
          <dl className="grid grid-cols-2 gap-y-2 text-sm">
            <dt className="text-muted-foreground">Username</dt>
            <dd className="font-mono">{user.username}</dd>
            <dt className="text-muted-foreground">Effective role</dt>
            <dd>
              <Badge title={user.effectiveRole}>
                {roleLabel(user.effectiveRole)}
              </Badge>
            </dd>
            <dt className="text-muted-foreground">Created</dt>
            <dd>
              {user.createdOn ? new Date(user.createdOn).toLocaleString() : "—"}
            </dd>
            <dt className="text-muted-foreground">Updated</dt>
            <dd>
              {user.updatedOn ? new Date(user.updatedOn).toLocaleString() : "—"}
            </dd>
          </dl>
        </div>

        <form
          onSubmit={handleSubmit}
          className="space-y-4 rounded-md border bg-card p-4"
          data-testid="user-edit-form"
        >
          <h2 className="text-lg font-semibold">Edit user</h2>

          <div className="space-y-2">
            <Label htmlFor="user-display-name">Display name</Label>
            <Input
              id="user-display-name"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              disabled={submitting}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="user-role">Role</Label>
            <Select
              value={role}
              onValueChange={(value) => setRole(value as Role)}
              disabled={submitting}
            >
              <SelectTrigger id="user-role" data-testid="user-role-trigger">
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
                data-testid="user-role-inline-error"
              >
                {roleFieldError}
              </p>
            )}
          </div>

          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Checkbox
                id="user-active"
                checked={active}
                onCheckedChange={(checked) => setActive(checked === true)}
                disabled={submitting}
              />
              <Label htmlFor="user-active">Active</Label>
            </div>
            {activeFieldError && (
              <p
                className="text-sm text-destructive"
                data-testid="user-active-inline-error"
              >
                {activeFieldError}
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label>Group memberships</Label>
            {allGroups.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                No groups available.
              </p>
            ) : (
              <div className="space-y-2" data-testid="user-groups-multiselect">
                {allGroups.map((g) => {
                  const checked = groupIds.includes(g.id);
                  return (
                    <div
                      key={g.id}
                      className="flex items-center gap-2"
                      data-group-id={g.id}
                    >
                      <Checkbox
                        id={`user-group-${g.id}`}
                        checked={checked}
                        onCheckedChange={(value) =>
                          toggleGroup(g.id, value === true)
                        }
                        disabled={submitting}
                      />
                      <Label htmlFor={`user-group-${g.id}`}>
                        {g.name}{" "}
                        <span
                          className="text-xs text-muted-foreground"
                          title={g.role}
                        >
                          ({roleLabel(g.role)})
                        </span>
                      </Label>
                    </div>
                  );
                })}
              </div>
            )}
            {groupsFieldError && (
              <p
                className="text-sm text-destructive"
                data-testid="user-groups-inline-error"
              >
                {groupsFieldError}
              </p>
            )}
          </div>

          <div className="flex justify-end">
            <Button
              type="submit"
              disabled={submitting}
              data-testid="user-edit-save"
            >
              <Save className="h-4 w-4 mr-1" />
              {submitting ? "Saving…" : "Save changes"}
            </Button>
          </div>
        </form>

        <ConfirmDialog
          open={deleteOpen}
          title="Delete user?"
          description={
            <>
              <p>
                This will permanently delete <strong>{user.username}</strong>{" "}
                and revoke all their sessions.
              </p>
              <p className="mt-2">This action cannot be undone.</p>
            </>
          }
          confirmLabel="Delete user"
          busy={deleteUserMutation.isPending}
          onConfirm={confirmDelete}
          onCancel={cancelDelete}
          data-testid="user-delete-confirm"
        />
      </div>
    </PageLayout>
  );
}
