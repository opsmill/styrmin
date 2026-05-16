import { Check, ChevronRight, Copy as CopyIcon } from "lucide-react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";
import {
  buildKubectlCommand,
  type KubectlCommandKind,
} from "./buildKubectlCommand";

interface KubectlCommandsProps {
  namespace: string;
  podName: string;
}

const COMMANDS: ReadonlyArray<{ kind: KubectlCommandKind; label: string }> = [
  { kind: "logs", label: "Logs" },
  { kind: "describe", label: "Describe" },
  { kind: "events", label: "Events" },
  { kind: "exec", label: "Exec" },
];

export function KubectlCommands({ namespace, podName }: KubectlCommandsProps) {
  return (
    <Collapsible className="rounded-lg border border-border bg-background">
      <CollapsibleTrigger className="group flex w-full items-center gap-2 px-3.5 py-2.5 text-left text-[13px] font-semibold text-foreground hover:bg-muted/40 data-[panel-open]:border-b data-[panel-open]:border-border">
        <ChevronRight className="h-3.5 w-3.5 text-muted-foreground transition-transform group-data-[panel-open]:rotate-90" />
        Commands
        <span className="text-xs font-normal text-muted-foreground">
          kubectl helpers for this pod
        </span>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <ul className="flex flex-col">
          {COMMANDS.map(({ kind, label }, i) => (
            <li
              key={kind}
              className={
                i < COMMANDS.length - 1
                  ? "border-b border-border/60"
                  : undefined
              }
            >
              <CommandRow
                label={label}
                command={buildKubectlCommand(kind, namespace, podName)}
              />
            </li>
          ))}
        </ul>
      </CollapsibleContent>
    </Collapsible>
  );
}

function CommandRow({ label, command }: { label: string; command: string }) {
  const { copied, copy } = useCopyToClipboard();
  return (
    <div className="flex items-center gap-3 px-3.5 py-2.5">
      <span className="w-16 shrink-0 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
      <pre className="flex-1 min-w-0 overflow-hidden whitespace-pre rounded border border-border/60 bg-muted/40 px-2.5 py-1.5 font-mono text-[12px] text-foreground">
        {command}
      </pre>
      <button
        type="button"
        onClick={() => copy(command)}
        aria-label={`Copy ${label.toLowerCase()} command`}
        data-testid={`copy-${label.toLowerCase()}-button`}
        className="inline-flex shrink-0 items-center gap-1.5 rounded-md border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground hover:bg-muted"
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
