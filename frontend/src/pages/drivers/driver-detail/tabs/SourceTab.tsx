import type { DriverVersionDetail } from "../types";

interface SourceTabProps {
  version: DriverVersionDetail;
}

/**
 * Source tab — renders the version's source location.
 *
 * Branches on `version.sourceType`:
 *   - "git":   repository URL, branch (when set), subpath (`sourcePath` when
 *              set). Per FR-012.
 *   - "local": local source path. Branch is intentionally NOT rendered
 *              per FR-013 / EC-006.
 *
 * Any unrecognised `sourceType` falls through to the git layout (treated as
 * a remote source) — this is the least surprising behaviour because a local
 * source is the explicit special case and everything else is "some kind of
 * remote".
 */
export function SourceTab({ version }: SourceTabProps) {
  if (version.sourceType === "local") {
    return <LocalSource path={version.sourcePath} />;
  }
  return (
    <GitSource
      repository={version.sourceRepository}
      branch={version.sourceBranch}
      path={version.sourcePath}
    />
  );
}

function GitSource({
  repository,
  branch,
  path,
}: {
  repository: string;
  branch: string | null | undefined;
  path: string | null | undefined;
}) {
  return (
    <dl
      className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-3 rounded-lg border border-border bg-card p-4"
      data-testid="driver-source-git"
    >
      <SourceRow label="Repository">
        <span
          className="font-mono text-sm break-all"
          data-testid="driver-source-repository"
        >
          {repository}
        </span>
      </SourceRow>
      {branch && (
        <SourceRow label="Branch">
          <span
            className="font-mono text-sm"
            data-testid="driver-source-branch"
          >
            {branch}
          </span>
        </SourceRow>
      )}
      {path && (
        <SourceRow label="Subpath">
          <span
            className="font-mono text-sm break-all"
            data-testid="driver-source-path"
          >
            {path}
          </span>
        </SourceRow>
      )}
    </dl>
  );
}

function LocalSource({ path }: { path: string | null | undefined }) {
  return (
    <dl
      className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-3 rounded-lg border border-border bg-card p-4"
      data-testid="driver-source-local"
    >
      <SourceRow label="Local path">
        <span
          className="font-mono text-sm break-all"
          data-testid="driver-source-path"
        >
          {path ?? ""}
        </span>
      </SourceRow>
    </dl>
  );
}

function SourceRow({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <>
      <dt className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground self-center">
        {label}
      </dt>
      <dd className="text-foreground">{children}</dd>
    </>
  );
}
