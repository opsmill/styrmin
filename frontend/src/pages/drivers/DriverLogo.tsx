import { useCallback, useState } from "react";
import { Package } from "lucide-react";
import { cn } from "@/lib/utils";

type DriverLogoSize = "sm" | "md";

/** `loading` shows the package icon while the image downloads. */
type LogoState = "loading" | "image" | "fallback";

const FRAME: Record<DriverLogoSize, string> = {
  sm: "h-5 w-5 rounded-md p-0.5",
  md: "h-8 w-8 rounded-lg p-1",
};

const FALLBACK_ICON: Record<DriverLogoSize, string> = {
  sm: "h-3 w-3",
  md: "h-4 w-4",
};

/**
 * Logo of a driver version from `spec.info.icon`, on a white tile so dark
 * logos stay visible in the dark theme. Shows the generic package icon until
 * the image has loaded, and when the version has none or the image fails.
 */
export function DriverLogo({
  icon,
  size = "md",
  loading = "lazy",
}: {
  icon?: string | null;
  size?: DriverLogoSize;
  /** `eager` for a logo that is always in view, such as a page header. */
  loading?: "lazy" | "eager";
}) {
  // Keyed by the URL so a new icon starts again in the loading state.
  return (
    <LogoFrame key={icon ?? ""} icon={icon} size={size} loading={loading} />
  );
}

function LogoFrame({
  icon,
  size,
  loading,
}: {
  icon?: string | null;
  size: DriverLogoSize;
  loading: "lazy" | "eager";
}) {
  const [state, setState] = useState<LogoState>(icon ? "loading" : "fallback");
  // A cached image can finish loading before React attaches `onLoad`.
  const imageRef = useCallback((img: HTMLImageElement | null) => {
    if (img?.complete && img.naturalWidth > 0) setState("image");
  }, []);
  return (
    <span
      data-testid="driver-logo"
      data-logo-state={state}
      className={cn(
        "relative flex shrink-0 items-center justify-center overflow-hidden border border-border",
        state === "image" ? "bg-white" : "bg-background",
        FRAME[size],
      )}
    >
      {icon && state !== "fallback" && (
        <img
          ref={imageRef}
          src={icon}
          alt=""
          referrerPolicy="no-referrer"
          loading={loading}
          decoding="async"
          onLoad={() => setState("image")}
          onError={() => setState("fallback")}
          className={cn(
            "h-full w-full object-contain",
            state === "loading" && "opacity-0",
          )}
        />
      )}
      {state !== "image" && (
        <Package
          aria-hidden="true"
          className={cn(
            FALLBACK_ICON[size],
            "text-muted-foreground",
            state === "loading" && "absolute inset-0 m-auto",
          )}
        />
      )}
    </span>
  );
}
