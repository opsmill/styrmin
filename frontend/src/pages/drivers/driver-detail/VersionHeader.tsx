import { Badge } from "@/components/ui/badge";
import type { DriverVersionDetail } from "./types";

interface VersionHeaderProps {
  version: DriverVersionDetail;
}

/**
 * Header above the right-pane tab strip. Surfaces the selected version's
 * identifying metadata: version label, source-type pill, supported-versions
 * text, and a source line.
 *
 * For git-sourced versions the source line is `repo @ branch · commit`; the
 * commit slot is intentionally left blank in v1 since the field is not yet
 * exposed by the API. For local-source versions the source line is the local
 * path; branch is intentionally omitted per FR-013.
 */
export function VersionHeader({ version }: VersionHeaderProps) {
  const isGit = version.sourceType === "git";

  return (
    <header className="flex flex-col gap-2" data-testid="driver-version-header">
      <div className="flex items-center gap-2">
        <h2 className="font-mono text-xl font-semibold text-foreground">
          {version.version}
        </h2>
        <Badge variant={isGit ? "secondary" : "outline"} className="uppercase">
          {isGit ? "git" : "local"}
        </Badge>
      </div>
      {version.supportedVersions && (
        <p className="text-sm text-muted-foreground">
          Supports {version.supportedVersions}
        </p>
      )}
      <p className="text-sm text-muted-foreground">
        {isGit ? (
          <GitSourceLine
            repository={version.sourceRepository}
            branch={version.sourceBranch}
            path={version.sourcePath}
          />
        ) : (
          <LocalSourceLine path={version.sourcePath} />
        )}
      </p>
    </header>
  );
}

function GitSourceLine({
  repository,
  branch,
  path,
}: {
  repository: string;
  branch: string | null | undefined;
  path: string | null | undefined;
}) {
  // `repo @ branch · commit` per the spec; commit is intentionally blank in v1.
  const segments: string[] = [];
  segments.push(branch ? `${repository} @ ${branch}` : repository);
  if (path) {
    segments.push(path);
  }
  return <span className="font-mono text-xs">{segments.join(" · ")}</span>;
}

function LocalSourceLine({ path }: { path: string | null | undefined }) {
  return <span className="font-mono text-xs">{path ?? ""}</span>;
}
