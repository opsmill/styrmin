import { Check, Copy as CopyIcon } from "lucide-react";
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";

interface NamespaceStripProps {
  namespace: string;
}

export function NamespaceStrip({ namespace }: NamespaceStripProps) {
  const { copied, copy } = useCopyToClipboard();
  return (
    <div
      data-testid="pods-namespace-strip"
      className="flex items-center gap-3.5 rounded-xl border border-border bg-muted/40 px-4 py-3"
    >
      <span className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
        Namespace
      </span>
      <span
        className="font-mono text-[13px] font-medium text-foreground"
        data-testid="pods-namespace-value"
      >
        {namespace}
      </span>
      <span className="flex-1" />
      <button
        type="button"
        onClick={() => copy(namespace)}
        aria-label="Copy namespace"
        data-testid="copy-namespace-button"
        className="inline-flex items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground hover:bg-muted"
      >
        {copied ? (
          <>
            <Check className="h-3.5 w-3.5" />
            Copied
          </>
        ) : (
          <>
            <CopyIcon className="h-3.5 w-3.5" />
            Copy
          </>
        )}
      </button>
    </div>
  );
}
