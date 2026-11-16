/**
 * Copies `text` to the clipboard and returns whether the copy worked.
 *
 * Browsers provide `navigator.clipboard` only in a secure context: a page
 * served over HTTPS or from localhost. When Styrmin is served over plain HTTP
 * from any other host, `navigator.clipboard` is `undefined`, so this falls
 * back to `document.execCommand("copy")`, which browsers still allow there
 * while the user's click is being handled (#603).
 *
 * Call it directly from the click handler, before any other `await`, so the
 * fallback runs while the click still counts as a user action.
 */
export async function copyText(text: string): Promise<boolean> {
  if (typeof navigator.clipboard?.writeText === "function") {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // The browser refused the write, for example because the page does not
      // have focus. Try the fallback below.
    }
  }
  return copyWithExecCommand(text);
}

/**
 * Selects `text` in a hidden element and runs the browser's copy command.
 *
 * The text is selected with a `Range` instead of focusing a `<textarea>`, so
 * keyboard focus stays on the button the user clicked and a modal dialog's
 * focus trap does not interfere. The `copy` listener writes exactly `text` as
 * plain text, so the clipboard does not hold rendered HTML.
 */
function copyWithExecCommand(text: string): boolean {
  const selection = document.getSelection();
  if (selection === null) return false;

  const holder = document.createElement("span");
  holder.textContent = text;
  holder.setAttribute("aria-hidden", "true");
  holder.style.position = "fixed";
  holder.style.top = "0";
  holder.style.clip = "rect(0, 0, 0, 0)";
  holder.style.whiteSpace = "pre";
  holder.style.userSelect = "text";

  const onCopy = (event: ClipboardEvent) => {
    if (event.clipboardData === null) return;
    event.clipboardData.setData("text/plain", text);
    event.preventDefault();
  };

  document.body.appendChild(holder);
  document.addEventListener("copy", onCopy);
  try {
    const range = document.createRange();
    range.selectNodeContents(holder);
    selection.removeAllRanges();
    selection.addRange(range);
    return document.execCommand("copy");
  } catch {
    return false;
  } finally {
    document.removeEventListener("copy", onCopy);
    selection.removeAllRanges();
    holder.remove();
  }
}
