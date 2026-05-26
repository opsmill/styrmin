import { Check, Copy as CopyIcon } from "lucide-react";
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";
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
 *   - "local": local source path. Branch is intentionally omitted for
 *              local sources per FR-013.
 *
 * Any unrecognised `sourceType` falls through to the git layout (treated as
 * a remote source) — this is the least surprising behaviour because a local
 * source is the explicit special case and everything else is "some kind of
 * remote".
 */
export function SourceTab({ version }: SourceTabProps) {
  const fingerprintRow = <FingerprintRows version={version} />;
  if (version.sourceType === "local") {
    return (
      <LocalSource path={version.sourcePath} fingerprintRow={fingerprintRow} />
    );
  }
  return (
    <GitSource
      repository={version.sourceRepository}
      branch={version.sourceBranch}
      path={version.sourcePath}
      fingerprintRow={fingerprintRow}
    />
  );
}

/**
 * Render the full provenance fingerprint rows (feature 013, T045): a
 * monospace code element with the full 64-char `contentHash` (local sources)
 * or 40-char `sourceCommitSha` (git sources), plus a copy-to-clipboard
 * button. Both can technically appear on the same row in pathological/legacy
 * data, so render whichever is populated independently.
 */
function FingerprintRows({ version }: { version: DriverVersionDetail }) {
  const contentHash = version.contentHash ?? null;
  const sourceCommitSha = version.sourceCommitSha ?? null;
  if (!contentHash && !sourceCommitSha) {
    return null;
  }
  return (
    <>
      {contentHash && (
        <SourceRow label="Content hash">
          <FingerprintValue
            value={contentHash}
            label="Copy content hash"
            testid="driver-source-content-hash"
          />
        </SourceRow>
      )}
      {sourceCommitSha && (
        <SourceRow label="Commit SHA">
          <FingerprintValue
            value={sourceCommitSha}
            label="Copy commit SHA"
            testid="driver-source-commit-sha"
          />
        </SourceRow>
      )}
    </>
  );
}

function FingerprintValue({
  value,
  label,
  testid,
}: {
  value: string;
  label: string;
  testid: string;
}) {
  const { copied, copy } = useCopyToClipboard();
  return (
    <span className="flex items-center gap-2">
      <code
        className="font-mono text-xs break-all text-foreground"
        data-testid={testid}
      >
        {value}
      </code>
      <button
        type="button"
        onClick={() => copy(value)}
        aria-label={label}
        data-testid={`${testid}-copy`}
        className="inline-flex shrink-0 items-center gap-1 rounded-md border border-border bg-background px-2 py-0.5 text-[11px] font-medium text-muted-foreground hover:bg-muted"
      >
        {copied ? (
          <>
            <Check className="h-3 w-3" aria-hidden />
            Copied
          </>
        ) : (
          <>
            <CopyIcon className="h-3 w-3" aria-hidden />
            Copy
          </>
        )}
      </button>
    </span>
  );
}

function GitSource({
  repository,
  branch,
  path,
  fingerprintRow,
}: {
  repository: string;
  branch: string | null | undefined;
  path: string | null | undefined;
  fingerprintRow: React.ReactNode;
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
      {fingerprintRow}
    </dl>
  );
}

function LocalSource({
  path,
  fingerprintRow,
}: {
  path: string | null | undefined;
  fingerprintRow: React.ReactNode;
}) {
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
      {fingerprintRow}
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
