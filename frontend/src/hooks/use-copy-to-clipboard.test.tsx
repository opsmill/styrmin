import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
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

// jsdom has no `document.execCommand`, the fallback that `copyText` uses when
// `navigator.clipboard` is missing or refuses the write.
function stubCopyCommand(result: boolean) {
  const execCommand = vi.fn().mockReturnValue(result);
  Object.defineProperty(document, "execCommand", {
    value: execCommand,
    configurable: true,
  });
  return execCommand;
}

describe("useCopyToClipboard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    Reflect.deleteProperty(navigator, "clipboard");
    Reflect.deleteProperty(document, "execCommand");
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

  it("flips copied to true on a page served over plain HTTP, where navigator.clipboard is missing (#603)", async () => {
    const execCommand = stubCopyCommand(true);
    const { result } = renderHook(() => useCopyToClipboard());

    let ok: boolean | undefined;
    await act(async () => {
      ok = await result.current.copy("x");
    });

    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(ok).toBe(true);
    expect(result.current.copied).toBe(true);
  });

  it("returns false and keeps copied false when writeText rejects and the copy command fails", async () => {
    const writeText = vi
      .fn<(text: string) => Promise<void>>()
      .mockRejectedValue(new Error("denied"));
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText },
      configurable: true,
      writable: true,
    });
    stubCopyCommand(false);

    const { result } = renderHook(() => useCopyToClipboard());
    let ok: boolean | undefined;
    await act(async () => {
      ok = await result.current.copy("x");
    });
    expect(ok).toBe(false);
    expect(result.current.copied).toBe(false);
  });
});
