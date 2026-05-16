import { useMemo, useState } from "react";
import { Copy, Check } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  deployment: {
    id: string;
    name: string;
    config: Record<string, unknown>;
  };
}

/**
 * Read-only modal that surfaces the raw persisted `Deployment.config` JSON
 * blob (snake_case, server-side shape) for operators who want the
 * machine-truth view.
 *
 * Uses the project's Base UI Dialog wrapper. Includes a "Copy" button that
 * writes the formatted JSON to the clipboard.
 */
export function ViewJsonDialog({ open, onOpenChange, deployment }: Props) {
  const [copied, setCopied] = useState(false);

  const formatted = useMemo(
    () => JSON.stringify(deployment.config, null, 2),
    [deployment.config],
  );

  async function handleCopy() {
    try {
      await navigator.clipboard.writeText(formatted);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch (err) {
      console.error("[ViewJsonDialog] clipboard write failed", err);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent data-testid="view-json-dialog" className="max-w-3xl gap-3">
        <DialogHeader>
          <DialogTitle>Configuration JSON</DialogTitle>
          <DialogDescription>
            Persisted server-side configuration for{" "}
            <code className="font-mono">{deployment.name}</code>.
          </DialogDescription>
        </DialogHeader>
        <pre
          data-testid="view-json-content"
          className="max-h-[60vh] overflow-auto rounded-md border border-border bg-muted/40 p-4 font-mono text-xs leading-relaxed"
        >
          {formatted}
        </pre>
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={handleCopy}
            data-testid="view-json-copy-button"
          >
            {copied ? (
              <>
                <Check className="h-3.5 w-3.5" /> Copied
              </>
            ) : (
              <>
                <Copy className="h-3.5 w-3.5" /> Copy
              </>
            )}
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={() => onOpenChange(false)}
            data-testid="view-json-close-button"
          >
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
