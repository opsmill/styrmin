import { useCallback, useEffect, useRef, useState } from "react";
import { copyText } from "@/lib/clipboard";

const RESET_AFTER_MS = 2_000;

export function useCopyToClipboard(): {
  copied: boolean;
  copy: (text: string) => Promise<boolean>;
} {
  const [copied, setCopied] = useState(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timeoutRef.current !== null) clearTimeout(timeoutRef.current);
    };
  }, []);

  const copy = useCallback(async (text: string): Promise<boolean> => {
    // Call `copyText` before any other `await`: its fallback for pages served
    // over plain HTTP works only while the click is being handled.
    if (!(await copyText(text))) {
      setCopied(false);
      return false;
    }
    setCopied(true);
    if (timeoutRef.current !== null) clearTimeout(timeoutRef.current);
    timeoutRef.current = setTimeout(() => {
      setCopied(false);
      timeoutRef.current = null;
    }, RESET_AFTER_MS);
    return true;
  }, []);

  return { copied, copy };
}
