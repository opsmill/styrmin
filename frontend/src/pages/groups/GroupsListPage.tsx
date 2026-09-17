import { useMemo, useState } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useQueryClient } from "@tanstack/react-query";
import { Pencil, Trash2, ChevronLeft, ChevronRight } from "lucide-react";

import {
  useListGroupsQuery,
  useListUsersQuery,
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
import { EmptyState } from "@/components/EmptyState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

import { CreateGroupDialog } from "./CreateGroupDialog";
import { useDocumentTitle } from "@/hooks/use-document-title";

type GroupRow = ListGroupsQuery["groups"][number];

const PAGE_SIZE = 25;

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

function roleBadgeVariant(role: Role): "default" | "secondary" | "outline" {
  if (role === "ADMIN") return "default";
  if (role === "READ_WRITE") return "secondary";
  return "outline";
}

export default function GroupsListPage() {
  useDocumentTitle("Groups");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<GroupRow | null>(null);

  const queryVariables = {
    search: search.trim() === "" ? null : search.trim(),
  };

  const { data, isLoading, error, refetch } =
    useListGroupsQuery(queryVariables);

  // Pull every active user to compute membership counts client-side. The
  // backend's `type Group` does not expose members.
  const usersQuery = useListUsersQuery({
    active: true,
    role: null,
    search: null,
  });

  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const deleteGroupMutation = useDeleteGroupMutation({
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["ListGroups"] });
      void queryClient.invalidateQueries({ queryKey: ["ListUsers"] });
      setPendingDelete(null);
    },
    onError: (err) => {
      const code = extractCode(err);
      const msg = err instanceof Error ? err.message : "Unknown error";
      if (code === "LAST_ADMIN") {
        setDeleteError(msg);
      } else {
        setDeleteError(msg);
      }
      setPendingDelete(null);
    },
  });

  const rows: GroupRow[] = useMemo(() => data?.groups ?? [], [data?.groups]);

  // Membership counts: for each group, count active users whose `.groups`
  // contains the group id.
  const memberCountByGroup = useMemo(() => {
    const counts = new Map<string, number>();
    for (const u of usersQuery.data?.users ?? []) {
      for (const g of u.groups) {
        counts.set(g.id, (counts.get(g.id) ?? 0) + 1);
      }
    }
    return counts;
  }, [usersQuery.data]);

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

  function handleDelete(group: GroupRow): void {
    setDeleteError(null);
    setPendingDelete(group);
  }

  function confirmDelete(): void {
    if (pendingDelete === null) return;
    deleteGroupMutation.mutate({ id: pendingDelete.id });
  }

  function cancelDelete(): void {
    if (deleteGroupMutation.isPending) return;
    setPendingDelete(null);
  }

  return (
    <PageLayout
      title="Groups"
      actions={<CreateGroupDialog onCreated={() => refetch()} />}
    >
      {/* Filters */}
      <div
        className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-3"
        data-testid="groups-filters"
      >
        <div className="space-y-1.5">
          <Label htmlFor="groups-filter-search">Search</Label>
          <Input
            id="groups-filter-search"
            placeholder="Group name"
            value={search}
            onChange={(e) => resetPagination(setSearch)(e.target.value)}
            data-testid="groups-filter-search"
          />
        </div>
      </div>

      {deleteError && (
        <Alert
          variant="destructive"
          className="mb-4"
          data-testid="groups-delete-error"
        >
          <AlertTitle>Cannot delete group</AlertTitle>
          <AlertDescription>{deleteError}</AlertDescription>
        </Alert>
      )}

      {isLoading && <LoadingState message="Loading groups..." />}

      {error && (
        <ErrorState message={error.message} onRetry={() => refetch()} />
      )}

      {data && rows.length === 0 && (
        <EmptyState
          title="No groups"
          description="No groups match the current filters."
        />
      )}

      {data && rows.length > 0 && (
        <>
          <div className="rounded-md border" data-testid="groups-table">
            <table className="w-full text-sm">
              <thead className="bg-muted/40">
                <tr>
                  <th className="px-4 py-2 text-left font-medium">Name</th>
                  <th className="px-4 py-2 text-left font-medium">Role</th>
                  <th className="px-4 py-2 text-left font-medium">
                    Active members
                  </th>
                  <th className="px-4 py-2 text-right font-medium">Actions</th>
                </tr>
              </thead>
              <tbody>
                {visibleRows.map((g) => (
                  <tr
                    key={g.id}
                    className="border-t"
                    data-testid="groups-row"
                    data-group-id={g.id}
                    data-group-name={g.name}
                  >
                    <td className="px-4 py-2">
                      <Link
                        to="/groups/$id"
                        params={{ id: g.id }}
                        className="hover:underline"
                      >
                        {g.name}
                      </Link>
                    </td>
                    <td className="px-4 py-2">
                      <Badge variant={roleBadgeVariant(g.role)} title={g.role}>
                        {roleLabel(g.role)}
                      </Badge>
                    </td>
                    <td
                      className="px-4 py-2 text-muted-foreground"
                      data-testid="groups-row-member-count"
                    >
                      {usersQuery.isLoading ? (
                        <span
                          className="text-xs"
                          data-testid="groups-row-member-count-loading"
                        >
                          Loading…
                        </span>
                      ) : usersQuery.error ? (
                        <span
                          title={usersQuery.error.message}
                          data-testid="groups-row-member-count-error"
                        >
                          —
                        </span>
                      ) : (
                        (memberCountByGroup.get(g.id) ?? 0)
                      )}
                    </td>
                    <td className="px-4 py-2 text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          size="sm"
                          variant="outline"
                          onClick={() =>
                            navigate({
                              to: "/groups/$id",
                              params: { id: g.id },
                            })
                          }
                          data-testid="groups-row-edit"
                        >
                          <Pencil className="h-3.5 w-3.5 mr-1" />
                          Edit
                        </Button>
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => handleDelete(g)}
                          data-testid="groups-row-delete"
                          disabled={deleteGroupMutation.isPending}
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
            title="Delete group?"
            description={
              pendingDelete === null ? (
                ""
              ) : (
                <>
                  <p>
                    This will permanently delete{" "}
                    <strong>{pendingDelete.name}</strong> and remove all of its
                    memberships.
                  </p>
                  <p className="mt-2">This action cannot be undone.</p>
                </>
              )
            }
            confirmLabel="Delete group"
            busy={deleteGroupMutation.isPending}
            onConfirm={confirmDelete}
            onCancel={cancelDelete}
            data-testid="groups-delete-confirm"
          />

          {rows.length > PAGE_SIZE && (
            <div
              className="mt-3 flex items-center justify-between text-sm"
              data-testid="groups-pagination"
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
                  data-testid="groups-pagination-prev"
                >
                  <ChevronLeft className="h-4 w-4" />
                  Previous
                </Button>
                <span data-testid="groups-pagination-page">
                  Page {safePage + 1} / {totalPages}
                </span>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() =>
                    setPage((p) => Math.min(totalPages - 1, p + 1))
                  }
                  disabled={safePage >= totalPages - 1}
                  data-testid="groups-pagination-next"
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
