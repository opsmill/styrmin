import { describe, it, expect } from "vitest";

import { repositoryOfFolderLink } from "@/pages/drivers/lib/repositoryUrl";

describe("repositoryOfFolderLink", () => {
  it.each([
    [
      "https://github.com/org/repo/tree/main/drivers/infrahub",
      "https://github.com/org/repo",
    ],
    [
      "https://github.com/org/repo/blob/main/drivers/a/driver.styrmin.yml",
      "https://github.com/org/repo",
    ],
    [
      "https://gitlab.com/group/sub/repo/-/tree/main/drivers/x",
      "https://gitlab.com/group/sub/repo",
    ],
    [
      "https://gitlab.example.com/group/repo/-/blob/main/x.yml",
      "https://gitlab.example.com/group/repo",
    ],
    // The user info of the link never reaches the message.
    [
      "https://user:token@github.com/org/repo/tree/main/x",
      "https://github.com/org/repo",
    ],
  ])("reads %s as a link into %s", (link, repository) => {
    expect(repositoryOfFolderLink(link)).toBe(repository);
  });

  it.each([
    "https://github.com/org/repo",
    "https://github.com/org/repo.git",
    "git@github.com:org/repo.git",
    "ssh://git@github.com/org/repo.git",
    "http://git-server:8080/simple-app.git",
    "/srv/repos/drivers",
    "not a url",
    "",
  ])("keeps %s", (value) => {
    expect(repositoryOfFolderLink(value)).toBeNull();
  });
});
