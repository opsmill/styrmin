#!/usr/bin/env python3
# RUN THIS SCRIPT, DO NOT READ IT: its output says what to fix. `--help` shows the options.
"""Short summary of a Helm chart: the facts a Styrmin driver needs, in about 100 lines.

Renders the chart with its default values (or with --values) and prints the workloads with
their labels, containers, images and ports, the Services, Ingresses, volumes, Helm hooks and
NetworkPolicies, then the value keys that drivers usually set. The full outputs stay in files
so they do not fill your context: read them with grep or sed when you need a detail.

Usage:
  python3 chart_summary.py <location> <chart-version> [--values file.yaml] [--out DIR]
  <location> is what driver.styrmin.yml takes: https://<repo>/<chart> or oci://<registry>/<path>/<chart>

Writes into --out (default ./chart-<name>-<version>): chart.yaml, values.yaml, render.yaml.
Requirements: helm 3+, Python 3.10+ with PyYAML.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml

KINDS_WITH_PODS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob"}
KEY_PATTERNS = re.compile(
    r"(fullnameOverride|nameOverride|extraDeploy|extraObjects|extraManifests|extraResources|additionalObjects|"
    r"additionalManifests|extraTemplates|extraK8sManifests|"
    r"networkPolicy|ingress|persistence|storageClass|existingSecret|password|secretKey|"
    r"superuser|admin|apiToken|allowedHosts|csrf|image|tag|registry|repository|"
    r"commonLabels|podLabels|labels|startupProbe|readinessProbe|livenessProbe|replicaCount|"
    r"enabled|architecture|auth|metrics|waitFor|init)",
    re.I,
)


def run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        err = proc.stderr.strip()[-2000:]
        hint = ""
        if cmd[:2] == ["helm", "template"] and ("execution error" in err or "required" in err.lower()):
            hint = ("\n\nThe chart refuses to render with its default values: it requires the value named in the "
                    "error. Run this script again with --set <key>=<value> for it (choose a fixed value: it will "
                    "also go into values.j2.yml), and pass the same --set to scaffold_driver.py.")
        sys.exit(f"command failed: {' '.join(cmd)}\n{err}{hint}")
    return proc.stdout


def oci_location_for(location: str, version: str) -> str | None:
    """The OCI location to use when an HTTP repository's index points this chart version to an
    oci:// URL (Bitnami does): FluxCD, which Styrmin uses, cannot follow such an entry."""
    import urllib.request
    if not location.startswith(("http://", "https://")):
        return None
    repo, chart = location.rstrip("/").rsplit("/", 1)
    req = urllib.request.Request(f"{repo}/index.yaml", headers={"User-Agent": "styrmin-driver-check/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            text = r.read().decode(errors="ignore")
    except Exception:  # noqa: BLE001
        return None
    m = re.search(r"^\s*-\s*(oci://\S+?/" + re.escape(chart) + r"):" + re.escape(version) + r"\s*$", text, re.M)
    return m.group(1) if m else None


def chart_args(location: str) -> list[str]:
    location = location.rstrip("/")
    if location.startswith("oci://"):
        return [location]
    repo, chart = location.rsplit("/", 1)
    return [chart, "--repo", repo]


def short_labels(labels: dict) -> str:
    skip = {"helm.sh/chart", "app.kubernetes.io/managed-by", "app.kubernetes.io/version", "chart", "heritage", "release"}
    return ", ".join(f"{k}={v}" for k, v in sorted(labels.items()) if k not in skip) or "-"


def pod_template(doc: dict) -> dict:
    spec = doc.get("spec") or {}
    if doc.get("kind") == "CronJob":
        return ((spec.get("jobTemplate") or {}).get("spec") or {}).get("template") or {}
    return spec.get("template") or {}


def value_paths(node: object, prefix: str = "", depth: int = 0) -> list[str]:
    """Paths of the default values whose key matches KEY_PATTERNS, with short scalar values."""
    out: list[str] = []
    if isinstance(node, dict) and depth < 4:
        for k, v in node.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                if KEY_PATTERNS.search(str(k)) and not v:
                    out.append(f"{path}: {{}}")
                out += value_paths(v, path, depth + 1)
            elif KEY_PATTERNS.search(str(k)):
                text = repr(v) if not isinstance(v, list) else f"[list of {len(v)}]"
                out.append(f"{path}: {text[:60]}")
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("location")
    p.add_argument("version")
    p.add_argument("--values", help="values file to render with (default: the chart defaults)")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="a value the chart needs to render, for example a required key (repeatable)")
    p.add_argument("--out", help="directory for the full outputs")
    p.add_argument("--all-values", action="store_true", help="list every matching value path, not the first 80")
    a = p.parse_args()

    name = a.location.rstrip("/").rsplit("/", 1)[-1]
    out = Path(a.out or f"chart-{name}-{a.version}")
    out.mkdir(parents=True, exist_ok=True)
    base = chart_args(a.location) + ["--version", a.version]

    chart_text = run(["helm", "show", "chart", *base])
    values_text = run(["helm", "show", "values", *base])
    (out / "chart.yaml").write_text(chart_text)
    (out / "values.yaml").write_text(values_text)
    render_cmd = ["helm", "template", "styrmin-test", *base, "--namespace", "test", "--skip-tests",
                  *[x for item in a.set for x in ("--set", item)]]
    if a.values:
        render_cmd += ["--values", a.values]
    render = run(render_cmd)
    (out / "render.yaml").write_text(render)

    chart = yaml.safe_load(chart_text) or {}
    print(f"# Chart {chart.get('name')} {chart.get('version')}  appVersion {chart.get('appVersion')}")
    for dep in chart.get("dependencies") or []:
        print(f"  subchart {dep.get('name')} {dep.get('version')} (condition {dep.get('condition')}) from {dep.get('repository')}")
        repo = str(dep.get("repository") or "")
        charts_dir = out / "pulled" / str(chart.get("name")) / "charts"
        def find_packaged() -> list[Path]:
            folder = charts_dir / dep["name"]
            return [folder] if (folder / "Chart.yaml").exists() else sorted(charts_dir.glob(f"{dep['name']}-*.tgz"))
        packaged = find_packaged() if (out / "pulled").exists() else []
        if not packaged and not (out / "pulled").exists():
            subprocess.run(["helm", "pull", *base, "--untar", "--untardir", str(out / "pulled")],
                           capture_output=True, text=True, timeout=300)
            packaged = find_packaged()
        ref: list[str] = []
        if packaged:
            ref = [str(packaged[-1])]
        elif repo.startswith(("oci://", "https://", "http://")) and not any(c in str(dep.get("version")) for c in "*^~x><"):
            ref = ([f"{repo.rstrip('/')}/{dep['name']}"] if repo.startswith("oci://") else [dep["name"], "--repo", repo]) \
                + ["--version", str(dep["version"])]
        if ref:
            proc = subprocess.run(["helm", "show", "values", *ref], capture_output=True, text=True, timeout=120)
            sub = yaml.safe_load(proc.stdout) if proc.returncode == 0 else None
            if isinstance(sub, dict):
                keys = [k for k in ("extraDeploy", "extraObjects", "networkPolicy", "fullnameOverride") if k in sub]
                print(f"    top-level keys in {dep['name']} values: {', '.join(keys) or 'none of extraDeploy/extraObjects/networkPolicy/fullnameOverride'}"
                      f"  (set them as {dep.get('alias') or dep['name']}.<key>)")
    print(f"  full files: {out}/chart.yaml, {out}/values.yaml, {out}/render.yaml")

    docs = [d for d in yaml.safe_load_all(render) if isinstance(d, dict) and d.get("kind")]
    print("\n# Workloads (labels on the workload | labels on its pods)")
    for d in docs:
        if d.get("kind") not in KINDS_WITH_PODS:
            continue
        meta = d.get("metadata") or {}
        tpl = pod_template(d)
        hook = (meta.get("annotations") or {}).get("helm.sh/hook")
        print(f"- {d['kind']}/{meta.get('name')}{'  HELM HOOK ' + hook if hook else ''}")
        print(f"    workload labels: {short_labels(meta.get('labels') or {})}")
        print(f"    pod labels:      {short_labels((tpl.get('metadata') or {}).get('labels') or {})}")
        spec = tpl.get("spec") or {}
        for kind, containers in (("init", spec.get("initContainers") or []), ("container", spec.get("containers") or [])):
            for c in containers:
                ports = ",".join(str(pt.get("containerPort")) for pt in c.get("ports") or []) or "-"
                probes = "/".join(x[:-5] for x in ("startupProbe", "readinessProbe", "livenessProbe") if c.get(x)) or "none"
                print(f"    {kind} {c.get('name')}: image {c.get('image')}  ports {ports}  probes {probes}")
        vols = [f"{v.get('name')}({'pvc' if 'persistentVolumeClaim' in v else next((k for k in v if k != 'name'), '?')})"
                for v in spec.get("volumes") or []]
        vols += [f"{(v.get('metadata') or {}).get('name')}(volumeClaimTemplate)" for v in (d.get("spec") or {}).get("volumeClaimTemplates") or []]
        if vols:
            print(f"    volumes: {', '.join(vols)}")
        if spec.get("serviceAccountName"):
            print(f"    serviceAccount: {spec['serviceAccountName']}")

    print("\n# Services")
    for d in docs:
        if d.get("kind") == "Service":
            ports = ", ".join(f"{pt.get('port')}->{pt.get('targetPort')}" for pt in (d.get("spec") or {}).get("ports") or [])
            print(f"- {d['metadata']['name']}  ports {ports}  selector {short_labels((d.get('spec') or {}).get('selector') or {})}")
    others: dict[str, list[str]] = {}
    for d in docs:
        if d.get("kind") not in KINDS_WITH_PODS | {"Service"}:
            others.setdefault(d["kind"], []).append(str((d.get("metadata") or {}).get("name")))
    print("\n# Other resources")
    for kind, names in sorted(others.items()):
        print(f"- {kind}: {', '.join(map(str, names))}")
    if "NetworkPolicy" not in others:
        print("- no NetworkPolicy with the default values")

    values = yaml.safe_load(values_text) or {}
    paths = value_paths(values)
    print(f"\n# Value keys drivers usually set ({len(paths)} found; grep {out}/values.yaml for details)")
    for line in paths if a.all_values else paths[:80]:
        print(f"  {line}")
    if len(paths) > 80 and not a.all_values:
        print(f"  ... {len(paths) - 80} more: run with --all-values, or grep {out}/values.yaml")


if __name__ == "__main__":
    main()
