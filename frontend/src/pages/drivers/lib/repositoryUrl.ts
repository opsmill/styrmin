/**
 * The repository URL of a web address that points at a folder or a file inside
 * a repository (a GitHub `/tree/` or `/blob/` link, or a GitLab `/-/tree/` or
 * `/-/blob/` link), or `null` for any other value. A clone needs the
 * repository URL, so the drawer refuses such a link before the load.
 */
export function repositoryOfFolderLink(value: string): string | null {
  let url: URL;
  try {
    url = new URL(value.trim());
  } catch {
    return null;
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return null;
  const gitlab = url.pathname.match(/^(.+?)\/-\/(?:tree|blob)\//);
  if (gitlab) return `${url.origin}${gitlab[1]}`;
  const github = url.pathname.match(/^(\/[^/]+\/[^/]+)\/(?:tree|blob)\//);
  if (github) return `${url.origin}${github[1]}`;
  return null;
}
