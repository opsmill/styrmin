import { useMemo, useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import {
  Pencil,
  Trash2,
  Check,
  X,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";

import {
  useListUsersQuery,
  useDeleteUserMutation,
  type ListUsersQuery,
  type Role,
} from "@/generated/graphql";
import { ROLE_OPTIONS, roleLabel } from "@/auth/roleLabel";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import { PageLayout } from "@/components/PageLayout";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

import { CreateUserDialog } from "./CreateUserDialog";
import { useDocumentTitle } from "@/hooks/use-document-title";

type UserRow = ListUsersQuery["users"][number];

type ActiveFilter = "any" | "true" | "false";
type RoleFilter = "any" | Role;

// The options of the two filters. Passed to each select's `items`, so that its
// trigger shows the label instead of the raw value.
const ACTIVE_FILTER_OPTIONS: ReadonlyArray<{
  value: ActiveFilter;
  label: string;
}> = [
  { value: "any", label: "Any" },
  { value: "true", label: "Yes" },
  { value: "false", label: "No" },
];
const ROLE_FILTER_OPTIONS: ReadonlyArray<{ value: RoleFilter; label: string }> =
  [{ value: "any", label: "Any" }, ...ROLE_OPTIONS];

const PAGE_SIZE = 25;

function roleBadgeVariant(role: Role): "default" | "secondary" | "outline" {
  if (role === "ADMIN") return "default";
  if (role === "READ_WRITE") return "secondary";
  return "outline";
}

export default function UsersListPage() {
  useDocumentTitle("Users");
  const [activeFilter, setActiveFilter] = useState<ActiveFilter>("any");
  const [roleFilter, setRoleFilter] = useState<RoleFilter>("any");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<UserRow | null>(null);

  const queryVariables = {
    active: activeFilter === "any" ? null : activeFilter === "true",
    role: roleFilter === "any" ? null : roleFilter,
    search: search.trim() === "" ? null : search.trim(),
  };

  const { data, isLoading, error, refetch } = useListUsersQuery(queryVariables);

  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const deleteUserMutation = useDeleteUserMutation({
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["ListUsers"] });
      setPendingDelete(null);
    },
    onError: (err) => {
      setDeleteError(err instanceof Error ? err.message : "Unknown error");
      setPendingDelete(null);
    },
  });

  const rows: UserRow[] = useMemo(() => data?.users ?? [], [data?.users]);
  const totalPages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages - 1);
  const visibleRows = useMemo(
    () => rows.slice(safePage * PAGE_SIZE, safePage * PAGE_SIZE + PAGE_SIZE),
    [rows, safePage],
  );

  function resetPagination<T>(setter: (next: T) => void): (next: T) => void {
    return (next: T) => {
      setter(next);
      setPage(0);
    };
  }

  function handleDelete(user: UserRow): void {
    setDeleteError(null);
    setPendingDelete(user);
  }

  function confirmDelete(): void {
    if (pendingDelete === null) return;
    deleteUserMutation.mutate({ id: pendingDelete.id });
  }

  function cancelDelete(): void {
    if (deleteUserMutation.isPending) return;
    setPendingDelete(null);
  }

  return (
    <PageLayout
      title="Users"
      actions={<CreateUserDialog onCreated={() => refetch()} />}
    >
      {/* Filters */}
      <div
        className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-3"
        data-testid="users-filters"
      >
        <div className="space-y-1.5">
          <Label htmlFor="users-filter-active">Active</Label>
          <Select
            items={ACTIVE_FILTER_OPTIONS}
            value={activeFilter}
            onValueChange={(value) =>
              resetPagination(setActiveFilter)(value as ActiveFilter)
            }
          >
            <SelectTrigger
              id="users-filter-active"
              data-testid="users-filter-active-trigger"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ACTIVE_FILTER_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="users-filter-role">Role</Label>
          <Select
            items={ROLE_FILTER_OPTIONS}
            value={roleFilter}
            onValueChange={(value) =>
              resetPagination(setRoleFilter)(value as RoleFilter)
            }
          >
            <SelectTrigger
              id="users-filter-role"
              data-testid="users-filter-role-trigger"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ROLE_FILTER_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="users-filter-search">Search</Label>
          <Input
            id="users-filter-search"
            placeholder="Username or display name"
            value={search}
            onChange={(e) => resetPagination(setSearch)(e.target.value)}
            data-testid="users-filter-search"
          />
        </div>
      </div>

      {deleteError && (
        <Alert
          variant="destructive"
          className="mb-4"
          data-testid="users-delete-error"
        >
          <AlertTitle>Cannot delete user</AlertTitle>
          <AlertDescription>{deleteError}</AlertDescription>
        </Alert>
      )}

      {isLoading && <LoadingState message="Loading users..." />}

      {error && (
        <ErrorState message={error.message} onRetry={() => refetch()} />
      )}

      {data && rows.length === 0 && (
        <EmptyState
          title="No users"
          description="No users match the current filters."
        />
      )}

      {data && rows.length > 0 && (
        <>
          <div className="rounded-md border" data-testid="users-table">
            <table className="w-full text-sm">
              <thead className="bg-muted/40">
                <tr>
                  <th className="px-4 py-2 text-left font-medium">Username</th>
                  <th className="px-4 py-2 text-left font-medium">
                    Display name
                  </th>
                  <th className="px-4 py-2 text-left font-medium">Role</th>
                  <th className="px-4 py-2 text-left font-medium">Groups</th>
                  <th className="px-4 py-2 text-left font-medium">Active</th>
                  <th className="px-4 py-2 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((u) => (
                  <tr
                    key={u.id}
                    className="border-t"
                    data-testid="users-row"
                    data-user-id={u.id}
                    data-username={u.username}
                  >
                    <td className="px-4 py-2">
                      <Link
                        to="/users/$id"
                        params={{ id: u.id }}
                        className="hover:underline"
                      >
                        {u.username}
                      </Link>
                    </td>
                    <td className="px-4 py-2">{u.displayName}</td>
                    <td className="px-4 py-2">
                      <Badge variant={roleBadgeVariant(u.role)} title={u.role}>
                        {roleLabel(u.role)}
                      </Badge>
                    </td>
                    <td className="px-4 py-2 text-muted-foreground">
                      {u.groups.length === 0
                        ? "—"
                        : u.groups.map((g) => g.name).join(", ")}
                    </td>
                    <td className="px-4 py-2">
                      {u.active ? (
                        <Check
                          className="h-4 w-4 text-success"
                          aria-label="active"
                        />
                      ) : (
                        <X
                          className="h-4 w-4 text-destructive"
                          aria-label="inactive"
                        />
                      )}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            navigate({
                              to: "/users/$id",
                              params: { id: u.id },
                            })
                          }
                          data-testid="users-row-edit"
                        >
                          <Pencil className="h-3.5 w-3.5 mr-1" />
                          Edit
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => handleDelete(u)}
                          data-testid="users-row-delete"
                          disabled={deleteUserMutation.isPending}
                        >
                          <Trash2 className="h-3.5 w-3.5 mr-1" />
                          Delete
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <ConfirmDialog
            open={pendingDelete !== null}
            title="Delete user?"
            description={
              pendingDelete === null ? (
                ""
              ) : (
                <>
                  <p>
                    This will permanently delete{" "}
                    <strong>{pendingDelete.username}</strong> and revoke all
                    their sessions.
                  </p>
                  <p className="mt-2">This action cannot be undone.</p>
                </>
              )
            }
            confirmLabel="Delete user"
            busy={deleteUserMutation.isPending}
            onConfirm={confirmDelete}
            onCancel={cancelDelete}
            data-testid="users-delete-confirm"
          />

          {rows.length > PAGE_SIZE && (
            <div
              className="mt-3 flex items-center justify-between text-sm"
              data-testid="users-pagination"
            >
              <div className="text-muted-foreground">
                Showing {safePage * PAGE_SIZE + 1}–
                {Math.min((safePage + 1) * PAGE_SIZE, rows.length)} of{" "}
                {rows.length}
              </div>
              <div className="flex items-center gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  disabled={safePage === 0}
                  data-testid="users-pagination-prev"
                >
                  <ChevronLeft className="h-4 w-4" />
                  Previous
                </Button>
                <span data-testid="users-pagination-page">
                  Page {safePage + 1} / {totalPages}
                </span>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    setPage((p) => Math.min(totalPages - 1, p + 1))
                  }
                  disabled={safePage >= totalPages - 1}
                  data-testid="users-pagination-next"
                >
                  Next
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </PageLayout>
  );
}
