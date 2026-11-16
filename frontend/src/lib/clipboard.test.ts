import { afterEach, describe, expect, it, vi } from "vitest";
import { copyText } from "./clipboard";

// jsdom matches a page served over plain HTTP: it has neither
// `navigator.clipboard` nor `document.execCommand`. Each test adds the ones it
// needs, and `afterEach` removes them again.

function stubClipboardApi(writeText: (text: string) => Promise<void>) {
  const mock = vi.fn(writeText);
  Object.defineProperty(navigator, "clipboard", {
    value: { writeText: mock },
    configurable: true,
  });
  return mock;
}

/**
 * Stubs `document.execCommand("copy")` the way a browser runs it: it fires a
 * `copy` event on the document and returns `result`. Records what was selected
 * when the command ran and what the `copy` listeners wrote as plain text.
 */
function stubCopyCommand(result = true) {
  const calls: Array<{
    selected: string;
    plainText?: string;
    prevented: boolean;
  }> = [];
  const execCommand = vi.fn((command: string) => {
    if (command !== "copy") return false;
    let plainText: string | undefined;
    const event = new Event("copy", { cancelable: true });
    Object.defineProperty(event, "clipboardData", {
      value: {
        setData: (type: string, value: string) => {
          if (type === "text/plain") plainText = value;
        },
      },
    });
    const selected = document.getSelection()?.toString() ?? "";
    document.dispatchEvent(event);
    calls.push({ selected, plainText, prevented: event.defaultPrevented });
    return result;
  });
  Object.defineProperty(document, "execCommand", {
    value: execCommand,
    configurable: true,
  });
  return { execCommand, calls };
}

afterEach(() => {
  Reflect.deleteProperty(navigator, "clipboard");
  Reflect.deleteProperty(document, "execCommand");
  document.body.innerHTML = "";
});

const COMMAND =
  "kubectl logs --namespace styrmin-abc api-7f9d4-jh2bn --all-containers";

describe("copyText", () => {
  it("writes with navigator.clipboard when the page has it (HTTPS or localhost)", async () => {
    const writeText = stubClipboardApi(() => Promise.resolve());
    const { execCommand } = stubCopyCommand();

    await expect(copyText(COMMAND)).resolves.toBe(true);

    expect(writeText).toHaveBeenCalledWith(COMMAND);
    expect(execCommand).not.toHaveBeenCalled();
  });

  it("copies with the copy command when navigator.clipboard is missing, as on a page served over plain HTTP", async () => {
    const { execCommand, calls } = stubCopyCommand();

    await expect(copyText(COMMAND)).resolves.toBe(true);

    expect(execCommand).toHaveBeenCalledWith("copy");
    expect(calls).toEqual([
      { selected: COMMAND, plainText: COMMAND, prevented: true },
    ]);
  });

  it("runs the copy command in the same task as the click, before any await", () => {
    const { execCommand } = stubCopyCommand();

    void copyText(COMMAND);

    expect(execCommand).toHaveBeenCalledTimes(1);
  });

  it("copies with the copy command when navigator.clipboard refuses the write", async () => {
    stubClipboardApi(() =>
      Promise.reject(new DOMException("denied", "NotAllowedError")),
    );
    const { calls } = stubCopyCommand();

    await expect(copyText(COMMAND)).resolves.toBe(true);

    expect(calls.map((call) => call.plainText)).toEqual([COMMAND]);
  });

  it("returns false when the browser reports that the copy command failed", async () => {
    stubCopyCommand(false);

    await expect(copyText(COMMAND)).resolves.toBe(false);
  });

  it("returns false when the browser has no copy command", async () => {
    await expect(copyText(COMMAND)).resolves.toBe(false);
  });

  it("keeps focus on the clicked button and leaves no hidden text, selection or copy listener behind", async () => {
    const button = document.createElement("button");
    document.body.appendChild(button);
    button.focus();
    const { calls } = stubCopyCommand();

    await copyText(COMMAND);

    expect(document.activeElement).toBe(button);
    expect(document.body.children).toHaveLength(1);
    expect(document.getSelection()?.rangeCount).toBe(0);

    // A later copy by the user is no longer rewritten.
    document.execCommand("copy");
    expect(calls[1]).toMatchObject({ plainText: undefined, prevented: false });
  });
});
