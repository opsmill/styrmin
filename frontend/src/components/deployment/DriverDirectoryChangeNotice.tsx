import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

interface Props {
  /** Driver directory of the deployment's driver version; `null` for the repository root. */
  current: string | null;
  /** The other driver directories the driver's versions come from. */
  others: ReadonlyArray<string | null>;
}

function DriverDirectory({ value }: { value: string | null }) {
  if (value === null) return <>the repository root</>;
  return <code className="break-all font-mono">{value}</code>;
}

/**
 * Upgrade-dialog warning: "Latest (auto)" picks the newest driver version from
 * any driver directory, so the upgrade can move the deployment to another one.
 */
export function DriverDirectoryChangeNotice({ current, others }: Props) {
  if (others.length === 0) return null;

  return (
    <Alert
      data-testid="driver-directory-change-notice"
      aria-labelledby="driver-directory-change-title"
      className="border-warning/50 bg-warning/10"
    >
      <AlertTitle id="driver-directory-change-title">
        The upgrade can change the driver directory
      </AlertTitle>
      <AlertDescription>
        <p>
          This deployment uses a driver version from{" "}
          <DriverDirectory value={current} />. Other versions of this driver
          come from{" "}
          {others.map((d, i) => (
            <span key={d ?? ""}>
              {i > 0 && ", "}
              <DriverDirectory value={d} />
            </span>
          ))}
          . Latest (auto) picks the newest version that supports the new
          application version from any of them. To stay in{" "}
          <DriverDirectory value={current} />, pick a version.
        </p>
      </AlertDescription>
    </Alert>
  );
}
