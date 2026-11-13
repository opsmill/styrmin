import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { GraphQLOperationError } from "@/lib/graphql-fetcher";
import { MessageWithLinks } from "@/components/MessageWithLinks";

interface Props {
  error: Error;
  /** Component names of the deployment, to name the one a replica parameter set. */
  componentNames: readonly string[];
  /** Closes the dialog and shows the Settings tab. */
  onOpenSettings: () => void;
}

function asText(value: unknown): string {
  return JSON.stringify(value) ?? String(value);
}

function DroppedIngressOverrideAlert({
  error,
  onOpenSettings,
}: {
  error: GraphQLOperationError;
  onOpenSettings: () => void;
}) {
  const service = String(error.extensions.service_name ?? "");
  return (
    <Alert variant="destructive" data-testid="upgrade-dropped-ingress-override">
      <AlertTitle>
        Clear the ingress override of {service} before you upgrade
      </AlertTitle>
      <AlertDescription className="space-y-2">
        <p>
          The new driver version does not build an Ingress for the service{" "}
          <code className="font-mono">{service}</code>, so its ingress override
          would stop applying. Nothing changed.
        </p>
        <ol className="list-decimal space-y-1 pl-5">
          <li>On the Settings tab, click Update Settings.</li>
          <li>In the Edit configuration drawer, open the Services section.</li>
          <li>
            Under Service ingress overrides, click Clear for{" "}
            <code className="font-mono">{service}</code>.
          </li>
          <li>Click Review &amp; apply, then upgrade again.</li>
        </ol>
        <p className="text-xs">
          <MessageWithLinks text={error.message} />
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onOpenSettings}
        >
          Open the Settings tab
        </Button>
      </AlertDescription>
    </Alert>
  );
}

/**
 * Error of the Upgrade dialog. Links in the server message are clickable. A
 * `RETIRED_PARAMETER_VALUE` rejection also lists the steps that fix it, which
 * happen on the Settings tab, not in this dialog (023). So does a
 * `SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED` rejection (#598): the server message
 * says to clear the override "in the same request", but this dialog sends only
 * the version, so the alert gives the steps in the configuration drawer.
 */
export function UpgradeErrorAlert({
  error,
  componentNames,
  onOpenSettings,
}: Props) {
  if (
    error instanceof GraphQLOperationError &&
    error.code === "SERVICE_INGRESS_OVERRIDE_WOULD_BE_DROPPED"
  ) {
    return (
      <DroppedIngressOverrideAlert
        error={error}
        onOpenSettings={onOpenSettings}
      />
    );
  }

  if (
    !(error instanceof GraphQLOperationError) ||
    error.code !== "RETIRED_PARAMETER_VALUE"
  ) {
    return (
      <Alert variant="destructive" data-testid="upgrade-error">
        <AlertDescription>
          <MessageWithLinks text={error.message} />
        </AlertDescription>
      </Alert>
    );
  }

  const parameter = String(error.extensions.parameter_name ?? "");
  const value = asText(error.extensions.value);
  const defaultValue = asText(error.extensions.default);
  // Driver versions before 023 named a count parameter `replicas_<component>`.
  const component = componentNames.find(
    (name) => `replicas_${name.replace(/-/g, "_")}` === parameter,
  );

  return (
    <Alert variant="destructive" data-testid="upgrade-retired-parameter">
      <AlertTitle>Change {parameter} before you upgrade</AlertTitle>
      <AlertDescription className="space-y-2">
        <p>
          The new driver version no longer declares the parameter{" "}
          <code className="font-mono">{parameter}</code>. This deployment sets
          it to <code className="font-mono">{value}</code>, and its default is{" "}
          <code className="font-mono">{defaultValue}</code>. Nothing changed.
        </p>
        <p>
          On the Settings tab, click Update Settings. In the Edit configuration
          drawer:
        </p>
        <ol className="list-decimal space-y-1 pl-5">
          {component && (
            <li>
              Under Components, set Replicas of{" "}
              <code className="font-mono">{component}</code> to{" "}
              <code className="font-mono">{value}</code>, so it keeps its pod
              count.
            </li>
          )}
          <li>
            Under Driver Parameters, set{" "}
            <code className="font-mono">{parameter}</code> back to{" "}
            <code className="font-mono">{defaultValue}</code>.
          </li>
          <li>Click Review &amp; apply, then upgrade again.</li>
        </ol>
        <p className="text-xs">
          <MessageWithLinks text={error.message} />
        </p>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={onOpenSettings}
        >
          Open the Settings tab
        </Button>
      </AlertDescription>
    </Alert>
  );
}
