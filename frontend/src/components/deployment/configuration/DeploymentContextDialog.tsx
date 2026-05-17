import { useState } from "react";
import { Dialog } from "@base-ui/react/dialog";
import { useQuery } from "@tanstack/react-query";
import { Check, Copy, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface Props {
  deploymentId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * Fetch the resolved `GlobalContext` JSON for a deployment.
 *
 * Same-origin REST call to the existing endpoint at
 * `GET /deployments/{deployment_id}/context`. We use `credentials: "include"`
 * so the SPA's session cookie rides along, matching how the GraphQL fetcher
 * authenticates.
 */
async function fetchDeploymentContext(deploymentId: string): Promise<unknown> {
  const response = await fetch(
    `/deployments/${encodeURIComponent(deploymentId)}/context`,
    {
      credentials: "include",
      headers: { Accept: "application/json" },
    },
  );
  if (!response.ok) {
    let detail = "";
    try {
      const body = (await response.json()) as { detail?: string };
      if (body?.detail) detail = `: ${body.detail}`;
    } catch {
      // ignore — fall back to status text
    }
    throw new Error(
      `Failed to load deployment context (${response.status} ${response.statusText})${detail}`,
    );
  }
  return response.json();
}

/**
 * Modal that surfaces the deployment's fully-resolved context JSON.
 *
 * Fetches lazily — the query is `enabled` only while `open` is true, so
 * users who never open the dialog don't pay for the round-trip. React
 * Query caches the response under `["deployment-context", deploymentId]`
 * so re-opening the dialog within the cache window is instant.
 */
export function DeploymentContextDialog({
  deploymentId,
  open,
  onOpenChange,
}: Props) {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ["deployment-context", deploymentId],
    queryFn: () => fetchDeploymentContext(deploymentId),
    enabled: open,
    staleTime: 30_000,
  });

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-40 bg-black/55" />
        <Dialog.Popup
          data-testid="deployment-context-dialog"
          className={cn(
            "fixed left-1/2 top-1/2 z-50 flex max-h-[85vh] w-[min(900px,90vw)]",
            "-translate-x-1/2 -translate-y-1/2 flex-col",
            "rounded-lg border border-border bg-background text-foreground shadow-2xl outline-none",
          )}
        >
          <header className="flex shrink-0 items-start justify-between gap-4 border-b border-border px-6 py-4">
            <div className="flex flex-col gap-1">
              <Dialog.Title className="text-base font-semibold text-foreground">
                Deployment context
              </Dialog.Title>
              <Dialog.Description className="text-xs text-muted-foreground">
                Fully-resolved context JSON delivered to the driver runtime.
              </Dialog.Description>
            </div>
            <Dialog.Close
              render={
                <button
                  type="button"
                  aria-label="Close deployment context"
                  data-testid="deployment-context-close-button"
                  className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                />
              }
            >
              <X className="h-4 w-4" />
            </Dialog.Close>
          </header>

          <div className="min-h-0 flex-1 overflow-hidden px-6 py-4">
            {isLoading ? (
              <p
                className="text-sm text-muted-foreground"
                data-testid="deployment-context-loading"
              >
                Loading context…
              </p>
            ) : isError ? (
              <div
                role="alert"
                data-testid="deployment-context-error"
                className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive"
              >
                {error instanceof Error
                  ? error.message
                  : "Failed to load deployment context."}
              </div>
            ) : (
              <ContextBody data={data} />
            )}
          </div>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/**
 * Renders the pretty-printed JSON with a "Copy" button. Pulled out so the
 * `useState` for copy feedback doesn't get re-mounted on every parent
 * loading/error transition.
 */
function ContextBody({ data }: { data: unknown }) {
  const [copied, setCopied] = useState(false);
  const formatted = JSON.stringify(data, null, 2);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(formatted);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // navigator.clipboard can fail in non-secure contexts — keep
      // silent rather than disrupting the read flow.
    }
  };

  return (
    <div className="flex h-full flex-col gap-2">
      <div className="flex justify-end">
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={handleCopy}
          data-testid="deployment-context-copy-button"
        >
          {copied ? (
            <>
              <Check className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
              Copied
            </>
          ) : (
            <>
              <Copy className="mr-1.5 h-3.5 w-3.5" aria-hidden="true" />
              Copy
            </>
          )}
        </Button>
      </div>
      <pre
        data-testid="deployment-context-json"
        className="min-h-0 flex-1 overflow-auto rounded-md border border-border bg-muted/40 p-3 font-mono text-xs leading-relaxed"
      >
        {formatted}
      </pre>
    </div>
  );
}
