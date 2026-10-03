import type { GetDeploymentQuery } from "@/generated/graphql";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { hasAppVersionToken } from "@/lib/image-reference";

type ImageOverride = NonNullable<
  GetDeploymentQuery["deployment"]
>["componentImageOverrides"][number];

interface Props {
  /** `Deployment.componentImageOverrides`. */
  overrides: readonly ImageOverride[];
}

/**
 * Upgrade-dialog warning (FR-008): applicable image overrides without the
 * `{{ app.version }}` token keep their image after the upgrade.
 */
export function PinnedImageOverridesNotice({ overrides }: Props) {
  const pinned = overrides
    .filter((o) => o.isApplicable && !hasAppVersionToken(o.reference))
    .sort((a, b) => a.component.localeCompare(b.component));
  if (pinned.length === 0) return null;

  return (
    <Alert
      data-testid="pinned-image-overrides-notice"
      aria-labelledby="pinned-image-overrides-title"
      className="border-warning/50 bg-warning/10"
    >
      <AlertTitle id="pinned-image-overrides-title">
        Pinned image overrides
      </AlertTitle>
      <AlertDescription>
        <p>These components keep their pinned image after the upgrade:</p>
        <ul className="mt-1 list-disc space-y-0.5 pl-5">
          {pinned.map((o) => (
            <li
              key={o.component}
              data-testid="pinned-image-override"
              data-component={o.component}
              data-reference={o.reference}
            >
              <span className="font-medium">{o.component}</span> (
              <code className="break-all font-mono">{o.reference}</code>)
            </li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  );
}
