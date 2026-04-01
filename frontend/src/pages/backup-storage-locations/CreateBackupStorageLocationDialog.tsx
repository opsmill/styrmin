import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod/v4";
import { useCreateBackupStorageLocationMutation } from "@/generated/graphql";
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
import { AlertCircle, Plus } from "lucide-react";
import { useState } from "react";

const createBslSchema = z.object({
  name: z.string().min(1, "Name is required"),
  endpoint: z.string().min(1, "S3 endpoint is required"),
  bucket: z.string().min(1, "Bucket name is required"),
  region: z.string().min(1, "Region is required"),
  accessKeyId: z.string().min(1, "Access key ID is required"),
  secretAccessKey: z.string().min(1, "Secret access key is required"),
});

type CreateBslValues = z.infer<typeof createBslSchema>;

export function CreateBackupStorageLocationDialog({
  onCreated,
}: {
  onCreated: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [, executeCreate] = useCreateBackupStorageLocationMutation();
  const [submitError, setSubmitError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<CreateBslValues>({
    resolver: zodResolver(createBslSchema),
    defaultValues: {
      name: "",
      endpoint: "",
      bucket: "",
      region: "",
      accessKeyId: "",
      secretAccessKey: "",
    },
  });

  const onSubmit = async (values: CreateBslValues) => {
    setSubmitError(null);
    const result = await executeCreate(values);

    if (result.error) {
      setSubmitError(result.error.message);
      return;
    }

    reset();
    setSubmitError(null);
    setOpen(false);
    onCreated();
  };

  const handleOpenChange = (nextOpen: boolean) => {
    setOpen(nextOpen);
    if (!nextOpen) {
      reset();
      setSubmitError(null);
    }
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button size="sm">
          <Plus className="h-4 w-4 mr-1" />
          New Storage Location
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Create Backup Storage Location</DialogTitle>
        </DialogHeader>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          {submitError && (
            <Alert variant="destructive">
              <AlertCircle className="h-4 w-4" />
              <AlertTitle>Error</AlertTitle>
              <AlertDescription>{submitError}</AlertDescription>
            </Alert>
          )}

          <div className="space-y-2">
            <Label htmlFor="bsl-name">Name</Label>
            <Input
              id="bsl-name"
              placeholder="my-backup-location"
              {...register("name")}
            />
            {errors.name && (
              <p className="text-sm text-destructive">{errors.name.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="bsl-endpoint">S3 Endpoint</Label>
            <Input
              id="bsl-endpoint"
              placeholder="https://s3.amazonaws.com"
              {...register("endpoint")}
            />
            {errors.endpoint && (
              <p className="text-sm text-destructive">
                {errors.endpoint.message}
              </p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="bsl-bucket">Bucket</Label>
              <Input
                id="bsl-bucket"
                placeholder="my-backup-bucket"
                {...register("bucket")}
              />
              {errors.bucket && (
                <p className="text-sm text-destructive">
                  {errors.bucket.message}
                </p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="bsl-region">Region</Label>
              <Input
                id="bsl-region"
                placeholder="us-east-1"
                {...register("region")}
              />
              {errors.region && (
                <p className="text-sm text-destructive">
                  {errors.region.message}
                </p>
              )}
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="bsl-access-key">Access Key ID</Label>
            <Input
              id="bsl-access-key"
              placeholder="AKIAIOSFODNN7EXAMPLE"
              {...register("accessKeyId")}
            />
            {errors.accessKeyId && (
              <p className="text-sm text-destructive">
                {errors.accessKeyId.message}
              </p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="bsl-secret-key">Secret Access Key</Label>
            <Input
              id="bsl-secret-key"
              type="password"
              placeholder="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
              {...register("secretAccessKey")}
            />
            {errors.secretAccessKey && (
              <p className="text-sm text-destructive">
                {errors.secretAccessKey.message}
              </p>
            )}
          </div>

          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => handleOpenChange(false)}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isSubmitting}>
              {isSubmitting ? "Creating..." : "Create"}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}
