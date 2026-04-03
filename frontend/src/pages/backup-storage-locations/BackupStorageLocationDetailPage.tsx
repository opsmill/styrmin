import { useParams, useNavigate } from "@tanstack/react-router";
import {
  useGetBackupStorageLocationQuery,
  useDeleteBackupStorageLocationMutation,
  useUpdateBackupStorageLocationMutation,
} from "@/generated/graphql";
import { useQueryClient } from "@tanstack/react-query";
import { PageLayout } from "@/components/PageLayout";
import { LoadingState } from "@/components/LoadingState";
import { ErrorState } from "@/components/ErrorState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertCircle, Trash2, KeyRound } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod/v4";

const updateCredentialsSchema = z.object({
  accessKeyId: z.string().min(1, "Access key ID is required"),
  secretAccessKey: z.string().min(1, "Secret access key is required"),
});

type UpdateCredentialsValues = z.infer<typeof updateCredentialsSchema>;

export default function BackupStorageLocationDetailPage() {
  const { id } = useParams({ from: "/backup-storage-locations/$id" });
  const navigate = useNavigate();
  const { data, isLoading, error, refetch } = useGetBackupStorageLocationQuery({
    backupStorageLocationId: id,
  });
  const deleteBslMutation = useDeleteBackupStorageLocationMutation();
  const updateBslMutation = useUpdateBackupStorageLocationMutation();
  const queryClient = useQueryClient();

  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [credentialsOpen, setCredentialsOpen] = useState(false);
  const [credentialsError, setCredentialsError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors: credErrors, isSubmitting: credSubmitting },
  } = useForm<UpdateCredentialsValues>({
    resolver: zodResolver(updateCredentialsSchema),
    defaultValues: { accessKeyId: "", secretAccessKey: "" },
  });

  const handleDelete = async () => {
    setDeleteError(null);
    try {
      await deleteBslMutation.mutateAsync({ backupStorageLocationId: id });
      queryClient.invalidateQueries({
        queryKey: ["ListBackupStorageLocations"],
      });
      navigate({ to: "/backup-storage-locations" });
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : "Unknown error");
    }
  };

  const onCredentialsSubmit = async (values: UpdateCredentialsValues) => {
    setCredentialsError(null);
    try {
      await updateBslMutation.mutateAsync({
        backupStorageLocationId: id,
        accessKeyId: values.accessKeyId,
        secretAccessKey: values.secretAccessKey,
      });
      queryClient.invalidateQueries({ queryKey: ["GetBackupStorageLocation"] });
      reset();
      setCredentialsOpen(false);
    } catch (err) {
      setCredentialsError(err instanceof Error ? err.message : "Unknown error");
    }
  };

  const bsl = data?.backupStorageLocation;

  return (
    <PageLayout
      title={bsl?.name ?? "Backup Storage Location"}
      breadcrumbs={[
        {
          label: "Backup Storage Locations",
          href: "/backup-storage-locations",
        },
        { label: bsl?.name ?? "..." },
      ]}
      actions={
        <div className="flex items-center gap-2">
          <Dialog open={credentialsOpen} onOpenChange={setCredentialsOpen}>
            <DialogTrigger asChild>
              <Button size="sm" variant="outline">
                <KeyRound className="h-4 w-4 mr-1" />
                Update Credentials
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Update Credentials</DialogTitle>
              </DialogHeader>
              <form
                onSubmit={handleSubmit(onCredentialsSubmit)}
                className="space-y-4"
              >
                {credentialsError && (
                  <Alert variant="destructive">
                    <AlertCircle className="h-4 w-4" />
                    <AlertTitle>Error</AlertTitle>
                    <AlertDescription>{credentialsError}</AlertDescription>
                  </Alert>
                )}
                <div className="space-y-2">
                  <Label htmlFor="cred-access-key">Access Key ID</Label>
                  <Input id="cred-access-key" {...register("accessKeyId")} />
                  {credErrors.accessKeyId && (
                    <p className="text-sm text-destructive">
                      {credErrors.accessKeyId.message}
                    </p>
                  )}
                </div>
                <div className="space-y-2">
                  <Label htmlFor="cred-secret-key">Secret Access Key</Label>
                  <Input
                    id="cred-secret-key"
                    type="password"
                    {...register("secretAccessKey")}
                  />
                  {credErrors.secretAccessKey && (
                    <p className="text-sm text-destructive">
                      {credErrors.secretAccessKey.message}
                    </p>
                  )}
                </div>
                <div className="flex justify-end gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => setCredentialsOpen(false)}
                  >
                    Cancel
                  </Button>
                  <Button type="submit" disabled={credSubmitting}>
                    {credSubmitting ? "Updating..." : "Update"}
                  </Button>
                </div>
              </form>
            </DialogContent>
          </Dialog>
          <Button size="sm" variant="destructive" onClick={handleDelete}>
            <Trash2 className="h-4 w-4 mr-1" />
            Delete
          </Button>
        </div>
      }
    >
      {isLoading && (
        <LoadingState message="Loading backup storage location..." />
      )}

      {error instanceof Error && (
        <ErrorState message={error.message} onRetry={() => refetch()} />
      )}

      {deleteError && (
        <Alert variant="destructive" className="mb-4">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Cannot Delete</AlertTitle>
          <AlertDescription>{deleteError}</AlertDescription>
        </Alert>
      )}

      {bsl && (
        <div className="space-y-6">
          <div className="rounded-md border">
            <table className="w-full text-sm">
              <tbody>
                <tr className="border-b">
                  <th className="px-4 py-2 text-left font-medium text-muted-foreground w-40">
                    Name
                  </th>
                  <td className="px-4 py-2">{bsl.name}</td>
                </tr>
                <tr className="border-b">
                  <th className="px-4 py-2 text-left font-medium text-muted-foreground">
                    Endpoint
                  </th>
                  <td className="px-4 py-2">{bsl.endpoint}</td>
                </tr>
                <tr className="border-b">
                  <th className="px-4 py-2 text-left font-medium text-muted-foreground">
                    Bucket
                  </th>
                  <td className="px-4 py-2">{bsl.bucket}</td>
                </tr>
                <tr className="border-b">
                  <th className="px-4 py-2 text-left font-medium text-muted-foreground">
                    Region
                  </th>
                  <td className="px-4 py-2">{bsl.region}</td>
                </tr>
                <tr className="border-b">
                  <th className="px-4 py-2 text-left font-medium text-muted-foreground">
                    Environments
                  </th>
                  <td className="px-4 py-2">{bsl.environmentCount}</td>
                </tr>
                <tr className="border-b">
                  <th className="px-4 py-2 text-left font-medium text-muted-foreground">
                    Created
                  </th>
                  <td className="px-4 py-2">
                    {new Date(bsl.createdOn).toLocaleString()}
                  </td>
                </tr>
                <tr>
                  <th className="px-4 py-2 text-left font-medium text-muted-foreground">
                    Updated
                  </th>
                  <td className="px-4 py-2">
                    {bsl.updatedOn
                      ? new Date(bsl.updatedOn).toLocaleString()
                      : "—"}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      )}
    </PageLayout>
  );
}
