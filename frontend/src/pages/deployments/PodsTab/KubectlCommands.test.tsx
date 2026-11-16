import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { KubectlCommands } from "./KubectlCommands";

// fireEvent instead of userEvent: userEvent.setup() installs its own
// `navigator.clipboard`, and these tests need the page to have none, as a
// page served over plain HTTP from a host other than localhost has none.

afterEach(() => {
  Reflect.deleteProperty(document, "execCommand");
});

describe("KubectlCommands copy buttons (#603)", () => {
  it("copies the logs command on a page that has no navigator.clipboard", async () => {
    const copied: string[] = [];
    Object.defineProperty(document, "execCommand", {
      configurable: true,
      value: vi.fn((command: string) => {
        if (command !== "copy") return false;
        const event = new Event("copy", { cancelable: true });
        Object.defineProperty(event, "clipboardData", {
          value: {
            setData: (_type: string, value: string) => copied.push(value),
          },
        });
        document.dispatchEvent(event);
        return true;
      }),
    });
    expect(navigator.clipboard).toBeUndefined();

    render(
      <KubectlCommands namespace="styrmin-abc" podName="api-7f9d4-jh2bn" />,
    );
    fireEvent.click(screen.getByRole("button", { name: /Commands/i }));
    fireEvent.click(await screen.findByTestId("copy-logs-button"));

    expect(copied).toEqual([
      "kubectl logs --namespace styrmin-abc api-7f9d4-jh2bn --all-containers",
    ]);
    expect(
      await screen.findByRole("button", { name: "Copy logs command" }),
    ).toHaveTextContent("Copied");
  });
});
