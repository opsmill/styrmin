import { describe, it, expect } from "vitest";
import { render, screen } from "@/test/utils";
import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it("renders Pending for PENDING status", async () => {
    await render(<StatusBadge status="PENDING" />);
    expect(screen.getByText("Pending")).toBeInTheDocument();
  });

  it("renders Running for RUNNING status", async () => {
    await render(<StatusBadge status="RUNNING" />);
    expect(screen.getByText("Running")).toBeInTheDocument();
  });

  it("renders Success for SUCCESS status", async () => {
    await render(<StatusBadge status="SUCCESS" />);
    expect(screen.getByText("Success")).toBeInTheDocument();
  });

  it("renders Failed for FAILED status", async () => {
    await render(<StatusBadge status="FAILED" />);
    expect(screen.getByText("Failed")).toBeInTheDocument();
  });

  it("renders the raw status string for unknown statuses", async () => {
    await render(<StatusBadge status="UNKNOWN" />);
    expect(screen.getByText("UNKNOWN")).toBeInTheDocument();
  });
});
