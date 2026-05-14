import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useCopyToClipboard } from "./use-copy-to-clipboard";

function stubClipboard() {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText },
    configurable: true,
    writable: true,
  });
  return writeText;
}

describe("useCopyToClipboard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  it("writes the given string to the clipboard and flips copied to true", async () => {
    const writeText = stubClipboard();
    const { result } = renderHook(() => useCopyToClipboard());

    expect(result.current.copied).toBe(false);
    await act(async () => {
      await result.current.copy(
        "kubectl logs --namespace ns pod --all-containers",
      );
    });

    expect(writeText).toHaveBeenCalledWith(
      "kubectl logs --namespace ns pod --all-containers",
    );
    expect(result.current.copied).toBe(true);
  });

  it("resets copied to false after 2s", async () => {
    stubClipboard();
    const { result } = renderHook(() => useCopyToClipboard());

    await act(async () => {
      await result.current.copy("x");
    });
    expect(result.current.copied).toBe(true);

    act(() => {
      vi.advanceTimersByTime(2_000);
    });
    expect(result.current.copied).toBe(false);
  });

  it("returns false and keeps copied false when writeText rejects", async () => {
    const writeText = vi
      .fn<(text: string) => Promise<void>>()
      .mockRejectedValue(new Error("denied"));
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
      writable: true,
    });

    const { result } = renderHook(() => useCopyToClipboard());
    let ok: boolean | undefined;
    await act(async () => {
      ok = await result.current.copy("x");
    });
    expect(ok).toBe(false);
    expect(result.current.copied).toBe(false);
  });
});
