import { useState } from "react";
import { Package } from "lucide-react";
import { cn } from "@/lib/utils";

type DriverLogoSize = "sm" | "md";

const FRAME: Record<DriverLogoSize, string> = {
  sm: "h-5 w-5 rounded-md p-0.5",
  md: "h-8 w-8 rounded-lg p-1",
};

const FALLBACK_ICON: Record<DriverLogoSize, string> = {
  sm: "h-3 w-3",
  md: "h-4 w-4",
};

/**
 * Logo of a driver version from `spec.info.icon`, or the generic package icon
 * when the version has none or the browser cannot load it.
 */
export function DriverLogo({
  icon,
  size = "md",
}: {
  icon?: string | null;
  size?: DriverLogoSize;
}) {
  // Keyed by the URL so a new icon starts again in the image state.
  return <LogoFrame key={icon ?? ""} icon={icon} size={size} />;
}

function LogoFrame({
  icon,
  size,
}: {
  icon?: string | null;
  size: DriverLogoSize;
}) {
  const [failed, setFailed] = useState(false);
  const showImage = !!icon && !failed;
  return (
    <span
      data-testid="driver-logo"
      data-logo-state={showImage ? "image" : "fallback"}
      className={cn(
        "flex shrink-0 items-center justify-center overflow-hidden border border-border bg-background",
        FRAME[size],
      )}
    >
      {showImage ? (
        <img
          src={icon}
          alt=""
          referrerPolicy="no-referrer"
          loading="lazy"
          decoding="async"
          onError={() => setFailed(true)}
          className="h-full w-full object-contain"
        />
      ) : (
        <Package
          aria-hidden="true"
          className={cn(FALLBACK_ICON[size], "text-muted-foreground")}
        />
      )}
    </span>
  );
}
