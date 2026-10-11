import {
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { cn } from "@/lib/utils";

const CLAMP = { 1: "line-clamp-1", 3: "line-clamp-3" } as const;

/**
 * Text cut to `lines` lines. When the text is longer, a "Show more" button
 * shows the rest, so keyboard and touch users can read it too.
 */
export function ClampedText({
  children,
  lines,
  className,
  "data-testid": testId,
}: {
  children: ReactNode;
  lines: keyof typeof CLAMP;
  /** Classes of the text itself. */
  className?: string;
  "data-testid"?: string;
}) {
  const id = useId();
  const textRef = useRef<HTMLParagraphElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [overflows, setOverflows] = useState(false);

  useLayoutEffect(() => {
    const text = textRef.current;
    if (!text || expanded) return;
    const measure = () => setOverflows(text.scrollHeight > text.clientHeight);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(text);
    return () => observer.disconnect();
  }, [children, expanded]);

  return (
    <div className="min-w-0">
      <p
        ref={textRef}
        id={id}
        data-testid={testId}
        className={cn(className, !expanded && CLAMP[lines])}
      >
        {children}
      </p>
      {(overflows || expanded) && (
        <button
          type="button"
          aria-controls={id}
          aria-expanded={expanded}
          onClick={() => setExpanded((value) => !value)}
          className="rounded-sm text-xs font-medium text-primary underline-offset-4 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          {expanded ? "Show less" : "Show more"}
        </button>
      )}
    </div>
  );
}
