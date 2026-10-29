#!/usr/bin/env python3
# RUN THIS SCRIPT, DO NOT READ IT: its output says what to fix. `--help` shows the options.
"""Finds the Helm charts of an application on Artifact Hub, official ones first.

Usage:
  python3 find_chart.py <application> [--limit 8]

Prints, for each chart: whether it is official or from a verified publisher, the chart name, its
latest version, the application version it ships, and the <location> to give the other scripts
and driver.styrmin.yml (`<repo-url>/<chart>`, or `oci://...` for an OCI repository).
Prefer the official chart; else the chart from the application's own organization.
Needs internet access; Python 3.10+ standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request

API = "https://artifacthub.io/api/v1/packages/search"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("application")
    p.add_argument("--limit", type=int, default=12)
    a = p.parse_args()
    query = urllib.parse.urlencode({"ts_query_web": a.application, "kind": 0, "limit": a.limit, "sort": "relevance"})
    req = urllib.request.Request(f"{API}?{query}", headers={"User-Agent": "styrmin-driver-skill"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
    except Exception as e:  # noqa: BLE001
        sys.exit(f"Artifact Hub did not answer ({e}). Find the chart in the application's documentation instead.")
    packages = data.get("packages") or []
    if not packages:
        sys.exit(f"No Helm chart named like {a.application!r} on Artifact Hub. Check the application's documentation.")
    app = a.application.lower()

    def own_repository(pk: dict) -> bool:
        """Published by the application's own organization or user on Artifact Hub."""
        repo = pk["repository"]
        owners = {str(repo.get("organization_name") or "").lower(), str(repo.get("user_alias") or "").lower()}
        return app in owners

    packages = [pk for pk in packages if a.application.lower() in pk["name"].lower()] or packages
    packages.sort(key=lambda pk: (not (pk.get("official") or pk["repository"].get("official")),
                                  not own_repository(pk), -(pk.get("stars") or 0),
                                  not pk["repository"].get("verified_publisher")))
    print(f"Helm charts for {a.application!r} (official, then the application's own organization, then most starred):")
    for pk in packages:
        repo = pk["repository"]
        url = str(repo.get("url", "")).rstrip("/")
        location = url if url.startswith("oci://") and url.endswith(f"/{pk['name']}") else f"{url}/{pk['name']}"
        flags = ", ".join(f for f, on in (("OFFICIAL", pk.get("official") or repo.get("official")),
                                           ("own repository", own_repository(pk)),
                                           ("verified publisher", repo.get("verified_publisher"))) if on) or "community"
        print(f"- {pk['name']} {pk.get('version')} (app {pk.get('app_version')})  [{flags}]  repository "
              f"{repo.get('name')}, {pk.get('stars') or 0} stars")
        print(f"    location: {location}")
    if not any(pk.get("official") or pk["repository"].get("official") or own_repository(pk) for pk in packages):
        print("\nNone of these is published by the application's own project. Check the application's "
              "documentation for an official Helm chart (some are not on Artifact Hub) before you take one of these.")
    print("\nNext: python3 <skill-dir>/scripts/chart_summary.py <location> <version> --out /tmp/chart")


if __name__ == "__main__":
    main()
