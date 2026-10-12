import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { CreateBackupStorageLocationDialog } from "@/pages/backup-storage-locations/CreateBackupStorageLocationDialog";

const createMutateAsync = vi.fn();

vi.mock("@/generated/graphql", async () => {
  const actual = await vi.importActual<typeof import("@/generated/graphql")>(
    "@/generated/graphql",
  );
  return {
    ...actual,
    useCreateBackupStorageLocationMutation: () => ({
      mutateAsync: createMutateAsync,
    }),
  };
});

function renderDialog() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={qc}>
      <CreateBackupStorageLocationDialog onCreated={() => {}} />
    </QueryClientProvider>,
  );
}

describe("CreateBackupStorageLocationDialog", () => {
  beforeEach(() => createMutateAsync.mockReset());

  it("shows each field's error message when submitted empty", async () => {
    const user = userEvent.setup();
    renderDialog();
    await user.click(
      screen.getByRole("button", { name: /new storage location/i }),
    );
    await user.click(screen.getByRole("button", { name: "Create" }));

    for (const message of [
      "Name is required",
      "S3 endpoint is required",
      "Bucket name is required",
      "Region is required",
      "Access key ID is required",
      "Secret access key is required",
    ]) {
      expect(await screen.findByText(message)).toBeInTheDocument();
    }
    expect(screen.queryByText("[object Object]")).not.toBeInTheDocument();
    expect(createMutateAsync).not.toHaveBeenCalled();
  });
});
