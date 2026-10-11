import * as React from "react";
import { Toast } from "@base-ui/react/toast";
import { AlertTriangle, Check, X } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * App-wide toast host. Wrap the app once (see App.tsx) so any view can raise a
 * transient notification via {@link useToast}. Built on Base UI's Toast (the
 * app's component library) — no extra dependency. Toasts auto-dismiss after the
 * provider timeout; a `type: "success"` toast gets the green check treatment
 * and a `type: "warning"` toast the amber triangle. Line breaks in a
 * description are kept.
 */
export function Toaster({ children }: { children: React.ReactNode }) {
  return (
    <Toast.Provider timeout={4000}>
      {children}
      <Toast.Portal>
        <Toast.Viewport className="fixed left-1/2 top-4 z-[100] flex w-[calc(100%-2rem)] max-w-sm -translate-x-1/2 flex-col gap-2 outline-none">
          <ToastList />
        </Toast.Viewport>
      </Toast.Portal>
    </Toast.Provider>
  );
}

function ToastList() {
  const { toasts } = Toast.useToastManager();
  return toasts.map((toast) => (
    <Toast.Root
      key={toast.id}
      toast={toast}
      className={cn(
        "flex items-start gap-3 rounded-lg border border-border bg-popover px-4 py-3 text-sm shadow-lg",
        "transition-all duration-200 ease-out",
        "data-[starting-style]:-translate-y-2 data-[starting-style]:opacity-0",
        "data-[ending-style]:-translate-y-2 data-[ending-style]:opacity-0",
      )}
    >
      {toast.type === "success" && (
        <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-success/10">
          <Check className="h-3.5 w-3.5 text-success" />
        </span>
      )}
      {toast.type === "warning" && (
        <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-warning/10">
          <AlertTriangle
            className="h-3.5 w-3.5 text-warning"
            aria-hidden="true"
          />
        </span>
      )}
      <div className="min-w-0 flex-1">
        <Toast.Title className="font-medium text-foreground">
          {toast.title}
        </Toast.Title>
        {toast.description && (
          <Toast.Description className="mt-0.5 whitespace-pre-line break-words text-muted-foreground">
            {toast.description}
          </Toast.Description>
        )}
      </div>
      <Toast.Close
        aria-label="Dismiss"
        className="-mr-1 shrink-0 rounded-md p-0.5 text-muted-foreground transition-colors hover:text-foreground focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <X className="h-4 w-4" />
      </Toast.Close>
    </Toast.Root>
  ));
}
