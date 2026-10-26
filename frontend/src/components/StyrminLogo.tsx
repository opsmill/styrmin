import { cn } from "@/lib/utils";

interface StyrminLogoProps {
  className?: string;
}

/** The Styrmin logo, the same drawing as `public/favicon.svg`. Decorative: label the parent instead. */
export function StyrminLogo({ className }: StyrminLogoProps) {
  return (
    <svg
      viewBox="0 0 64 64"
      aria-hidden="true"
      focusable="false"
      data-testid="styrmin-logo"
      // The ring outlines the dark tile against the dark theme's background.
      className={cn(
        "shrink-0 rounded-[22%] ring-1 ring-foreground/15",
        className,
      )}
    >
      <rect width="64" height="64" rx="14" fill="#231556" />
      <g transform="translate(0 1)">
        <line
          x1="32"
          y1="11"
          x2="32"
          y2="29"
          stroke="#FFFFFF"
          strokeWidth="3"
          strokeLinecap="round"
        />
        <polygon points="33.5,11 46,15.5 33.5,20" fill="#63CDD4" />
        <polygon points="11,29 53,29 50.75,35 13.25,35" fill="#FFFFFF" />
        <polygon points="14.38,38 49.62,38 47.38,44 16.62,44" fill="#63CDD4" />
        <polygon points="17.75,47 46.25,47 44,53 20,53" fill="#84A0CC" />
      </g>
    </svg>
  );
}
