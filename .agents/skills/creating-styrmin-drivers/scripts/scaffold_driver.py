#!/usr/bin/env python3
# RUN THIS SCRIPT, DO NOT READ IT: its output says what to fix. `--help` shows the options.
"""Writes a first draft of a Styrmin driver from a Helm chart. Fix it with check_driver.py.

Usage:
  python3 scaffold_driver.py <driver-dir> <driver-name> <location> <chart-version> [--app-version X.Y.Z]
  <location>: https://<repo>/<chart> or oci://<registry>/<path>/<chart>

It renders the chart with its default values and writes into <driver-dir>:
  driver.styrmin.yml  a component for each Deployment and StatefulSet (labels present on both the
                      workload and its pods, the most specific label first, the first container),
                      an external service for the workload behind the chart's Ingress, backups for
                      data stores
  values.j2.yml       fullnameOverride for the chart and each subchart, storage classes from the
                      context, the image tag from {{ app.version }}, the egress NetworkPolicy in an
                      extra-objects value, and TODO lines for what only you can decide
  README.md           a skeleton to complete
It refuses to overwrite existing files unless you pass --force.
Every TODO needs a decision. Then run check_driver.py and fix each FAIL.
Requirements: helm 3+, Python 3.10+ with PyYAML.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chart_summary import chart_args, pod_template, run  # noqa: E402

EXCLUDED_LABELS = {"helm.sh/chart", "app.kubernetes.io/managed-by", "app.kubernetes.io/version",
                   "app.kubernetes.io/instance", "heritage", "release", "chart", "pod-template-hash", "version",
                   "app.kubernetes.io/part-of"}
PREFERRED_LABELS = ["app.kubernetes.io/component", "app.kubernetes.io/name", "component", "app", "service"]
GENERIC_COMPONENTS = {"primary", "master", "main", "server", "replica", "replicas", "node"}
BACKUP_BY_IMAGE = [("postgres", "postgres"), ("mariadb", "mariadb"), ("mysql", "mariadb"),
                   ("mongo", "mongodb"), ("neo4j", "neo4j")]
CACHE_IMAGES = ("redis", "valkey", "memcached", "keydb", "dragonfly")
SECRET_KEY = re.compile(r"(password|secret|token|pepper|key)$", re.I)


EXTRA_OBJECT_KEYS = ("extraDeploy", "extraObjects", "extraManifests", "extraResources", "additionalObjects",
                     "additionalManifests", "extraTemplates", "extraK8sManifests")


def sub_fullname(key: str) -> str:
    """fullnameOverride for a subchart: lowercase (Kubernetes names), short (names add the release name)."""
    k = re.sub(r"[^a-z0-9-]+", "-", re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "-", key).lower()).strip("-")
    if len(k) > 12:
        k = "".join(part[0] for part in k.split("-") if part)
    return f"styrmin-{k}"


def is_credential(key: str, value) -> bool:
    """A value that holds a credential, not the name of a key in a Secret or a switch."""
    if isinstance(value, (dict, bool)) or not SECRET_KEY.search(key):
        return False
    if key.lower().startswith(("existing", "automount")) or key.lower().endswith("fromsecret"):
        return False
    if key.endswith("Key") and key not in ("secretKey", "apiKey") and isinstance(value, str) and value \
            and re.fullmatch(r"[A-Za-z0-9_.-]+", value) and not key.lower().endswith(("hashkey", "encryptionkey")):
        return False
    return True

POLICY = """\
- apiVersion: networking.k8s.io/v1
  kind: NetworkPolicy
  metadata:
    name: styrmin-{name}-egress
  spec:
    podSelector: {{}}
    policyTypes: [Egress]
    egress:
      # DNS
      - to:
          - namespaceSelector: {{}}
            podSelector:
              matchExpressions:
                - key: k8s-app
                  operator: In
                  values: [kube-dns, coredns]
        ports:
          - port: 53
            protocol: UDP
          - port: 53
            protocol: TCP
      # The other pods of this deployment (application -> database, cache, queue)
      - to:
          - podSelector: {{}}
      # TODO internet: keep this rule only when the application needs the internet
      # - to:
      #     - ipBlock:
      #         cidr: 0.0.0.0/0
      #         except: [10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 100.64.0.0/10]
"""


def newest_legacy_tag(name: str) -> str | None:
    """The newest `<x.y.z>-debian-<n>-r<m>` tag of docker.io/bitnamilegacy/<name>, or None."""
    import json
    import urllib.request
    best: tuple | None = None
    url = f"https://hub.docker.com/v2/repositories/bitnamilegacy/{name}/tags?page_size=100&ordering=last_updated"
    for _ in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "styrmin-driver-skill"}), timeout=20) as r:
                data = json.loads(r.read())
        except Exception:  # noqa: BLE001
            return None
        for t in data.get("results") or []:
            m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)-debian-(\d+)-r(\d+)", t.get("name", ""))
            if m:
                key = tuple(int(x) for x in m.groups())
                if best is None or key > best[0]:
                    best = (key, t["name"])
        url = data.get("next")
        if not url:
            break
    return best[1] if best else None


def discover_ingress(values: dict, base: list[str], driver_name: str) -> tuple[list[tuple[str, str]], str]:
    """Finds how the chart sets its Ingress hosts when they are not a list of {host: ...} entries.

    Switches each `<...>.ingress.enabled` value on, renders the chart, reads the Ingress hosts it
    produces, and finds the values that hold those hosts (a string, or a list of strings). Returns
    the settings to write (dotted path, YAML value) and a note for the values file."""
    primary = f"{{{{ services['{driver_name}'].primary_fqdn }}}}"
    readable = f"{{{{ services['{driver_name}'].human_readable_fqdn }}}}"
    candidates = sorted(find_paths(values, lambda k, v: k == "ingress" and isinstance(v, dict) and "enabled" in v),
                        key=lambda p: p.count("."))[:4]
    for cand in candidates:
        proc = subprocess.run(["helm", "template", "styrmin-test", *base, "--namespace", "test", "--skip-tests",
                               "--set", f"{cand}.enabled=true"], capture_output=True, text=True, timeout=300)
        if proc.returncode != 0:
            continue
        hosts = []
        ingresses = 0
        for d in yaml.safe_load_all(proc.stdout):
            if isinstance(d, dict) and d.get("kind") == "Ingress":
                ingresses += 1
                hosts += [r.get("host") for r in (d.get("spec") or {}).get("rules") or [] if r.get("host")]
        block = get_path(values, cand) or {}
        if not hosts and isinstance(block.get("hosts"), list) and not block["hosts"]:
            # An empty list of hosts: find whether it takes strings or {host, paths} entries.
            probe = "probe.styrmin.invalid"
            for fmt, value, yaml_value in (
                    ("strings", f'["{probe}"]', f'["{primary}", "{readable}"]'),
                    ("entries", f'[{{"host": "{probe}", "paths": [{{"path": "/", "pathType": "Prefix"}}]}}]',
                     f'[{{host: "{primary}", paths: [{{path: /, pathType: Prefix}}]}}, '
                     f'{{host: "{readable}", paths: [{{path: /, pathType: Prefix}}]}}]')):
                probe_run = subprocess.run(["helm", "template", "styrmin-test", *base, "--namespace", "test",
                                            "--skip-tests", "--set", f"{cand}.enabled=true",
                                            "--set-json", f"{cand}.hosts={value}"],
                                           capture_output=True, text=True, timeout=300)
                if probe_run.returncode == 0 and re.search(rf"host:\s*[\"']?{re.escape(probe)}", probe_run.stdout):
                    return ([(f"{cand}.enabled", "true"), (f"{cand}.hosts", yaml_value)],
                            f"# Ingress: switched on with {cand}.enabled; its hosts are {cand}.hosts (a list of "
                            f"{fmt}). Do not set the ingress class: Styrmin sets it.")
        if ingresses and not hosts:
            # The Ingress renders without a host: set the empty host value of this ingress block.
            key = next((k for k in ("hostName", "hostname", "host") if k in block and isinstance(block[k], (str, type(None)))), None)
            if key:
                return ([(f"{cand}.enabled", "true"), (f"{cand}.{key}", f'"{primary}"')],
                        f"# Ingress: switched on with {cand}.enabled; its host is {cand}.{key}. Do not set the ingress "
                        "class: Styrmin sets it.\n# TODO ingress: this value takes one host. When the chart has a value for "
                        f"extra hosts,\n# add \"{readable}\" there too.")
        if not hosts:
            continue
        settings: list[tuple[str, str]] = [(f"{cand}.enabled", "true")]
        placed = False
        for h in dict.fromkeys(hosts):
            scalar = find_paths(values, lambda k, v, h=h: v == h)
            listed = find_paths(values, lambda k, v, h=h: isinstance(v, list) and h in v)
            entries = find_paths(values, lambda k, v, h=h: isinstance(v, list)
                                 and any(isinstance(e, dict) and e.get("host") == h for e in v))
            if entries:
                sample = next(e for e in get_path(values, entries[0]) if isinstance(e, dict) and e.get("host") == h)
                both = [dict(sample, host=primary), dict(sample, host=readable)]
                settings.append((entries[0], json.dumps(both)))
                placed = True
                break
            if listed:
                settings.append((listed[0], f'["{primary}", "{readable}"]'))
                placed = True
                break
            if scalar:
                settings.append((scalar[0], f'"{primary}"'))
                placed = True
                break
        if placed:
            note = (f"# Ingress: switched on with {cand}.enabled; the chart takes its host from "
                    f"{settings[1][0]}. Do not set the ingress class: Styrmin sets it.")
            if not settings[1][1].startswith("["):  # one host: a string value
                note += ("\n# TODO ingress: this value takes one host. When the chart has a value for extra hosts,"
                         f"\n# add \"{readable}\" there too.")
            return settings, note
    return [], ""


def labels(obj: dict | None) -> dict:
    return dict(((obj or {}).get("metadata") or {}).get("labels") or {})


def is_hook(d: dict) -> bool:
    return "helm.sh/hook" in ((d.get("metadata") or {}).get("annotations") or {})


def matches(selector: dict, lab: dict) -> bool:
    return all(lab.get(k) == v for k, v in selector.items())


def get_path(values: dict, path: str):
    node = values
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def find_paths(node, predicate, prefix: str = "", depth: int = 0) -> list[str]:
    out: list[str] = []
    if isinstance(node, dict) and depth < 6:
        for k, v in node.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            if predicate(str(k), v):
                out.append(path)
            out += find_paths(v, predicate, path, depth + 1)
    return out


# The only Jinja expressions the scaffold writes itself. Any other Jinja delimiter in the draft comes
# from the chart (a Helm `tpl` string, or a payload), and Styrmin and check_driver.py would run it.
OWN_JINJA = re.compile(r"\{\{ (?:services\['[A-Za-z0-9_.-]+'\]\.(?:primary_fqdn|human_readable_fqdn)"
                       r"|instance\.config\.standard_storage\.storage_class|app\.version) \}\}")
JINJA_START = re.compile(r"\{[{%#]")


def escape_chart_jinja(text: str) -> str:
    """Makes every Jinja delimiter literal text, except in the scaffold's own expressions."""
    def literal(part: str) -> str:
        return JINJA_START.sub(lambda m: "{% raw %}" + m.group() + "{% endraw %}", part)

    out, pos = [], 0
    for m in OWN_JINJA.finditer(text):
        out += [literal(text[pos:m.start()]), m.group()]
        pos = m.end()
    return "".join([*out, literal(text[pos:])])


def nested(paths_values: list[tuple[str, str]], indent: int = 0) -> str:
    """Renders dotted paths with already-quoted scalar values as nested YAML lines."""
    tree: dict = {}
    for path, value in paths_values:
        node = tree
        parts = path.split(".")
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = value
    lines: list[str] = []

    def walk(node: dict, level: int) -> None:
        for k, v in node.items():
            if isinstance(v, dict):
                lines.append(" " * level + f"{k}:")
                walk(v, level + 2)
            else:
                lines.append(" " * level + f"{k}: {v}")
    walk(tree, indent)
    return "\n".join(lines)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("driver_dir", type=Path)
    p.add_argument("driver_name")
    p.add_argument("location")
    p.add_argument("version")
    p.add_argument("--app-version")
    p.add_argument("--force", action="store_true")
    p.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                   help="a chart value to render with, for example postgresql-ha.enabled=false (repeatable); "
                        "it is also written into values.j2.yml")
    a = p.parse_args()

    out: Path = a.driver_dir
    out.mkdir(parents=True, exist_ok=True)
    for f in ("driver.styrmin.yml", "values.j2.yml", "README.md"):
        if (out / f).exists() and not a.force:
            sys.exit(f"{out / f} exists: pass --force to overwrite it")

    location = a.location.rstrip("/")
    from chart_summary import oci_location_for
    oci = oci_location_for(location, a.version)
    if oci:
        print(f"The repository index points this chart to {oci}: using that OCI location, which Styrmin can pull.")
        location = oci
    base = chart_args(location) + ["--version", a.version]
    chart = yaml.safe_load(run(["helm", "show", "chart", *base])) or {}
    values = yaml.safe_load(run(["helm", "show", "values", *base])) or {}
    user_sets: list[tuple[str, str]] = []
    for item in a.set:
        key, _, raw = item.partition("=")
        val = yaml.safe_load(raw) if raw else ""
        node = values
        parts = key.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {}) if isinstance(node.get(part), dict) or part not in node else node[part]
        node[parts[-1]] = val
        user_sets.append((key, raw if raw else '""'))
    set_args = [x for item in a.set for x in ("--set", item)]
    base = base + set_args
    render = run(["helm", "template", "styrmin-test", *base, "--namespace", "test", "--skip-tests"])
    docs = [d for d in yaml.safe_load_all(render) if isinstance(d, dict) and d.get("kind")]
    chart_name = str(chart.get("name"))

    tmp = Path(tempfile.mkdtemp(prefix="scaffold-"))
    run(["helm", "pull", *[x for x in base if x not in set_args], "--untar", "--untardir", str(tmp)])
    sub_values: dict[str, dict] = {}
    library: set[str] = set()
    disabled: list[str] = []
    for dep in chart.get("dependencies") or []:
        key = dep.get("alias") or dep["name"]
        condition = str(dep.get("condition") or "")
        if condition and any(get_path(values, c.strip()) is False for c in condition.split(",")):
            disabled.append(key)
            continue
        folder = tmp / chart_name / "charts" / dep["name"]
        if (folder / "Chart.yaml").exists():
            if (yaml.safe_load((folder / "Chart.yaml").read_text()) or {}).get("type") == "library":
                library.add(key)
                continue
            sub_values[key] = yaml.safe_load((folder / "values.yaml").read_text()) if (folder / "values.yaml").exists() else {}
        else:
            sub_values[key] = {}

    # Render again with the names the driver sets, so that container names built from the release
    # or full name (some charts name a container after it) match what Styrmin will deploy.
    overrides: dict[str, object] = {"fullnameOverride": f"styrmin-{chart_name}"}
    for key in sub_values:
        overrides[key] = {"fullnameOverride": sub_fullname(key)}
    (tmp / "overrides.yaml").write_text(yaml.safe_dump(overrides))
    render = run(["helm", "template", "styrmin-test", *base, "--namespace", "test", "--skip-tests",
                  "--values", str(tmp / "overrides.yaml")])
    docs = [d for d in yaml.safe_load_all(render) if isinstance(d, dict) and d.get("kind")]

    # Hosts that the main chart builds from the release name, while the Service follows the
    # subchart's fullnameOverride: the application would look for a host that does not exist.
    import base64 as b64
    service_names = {(d.get("metadata") or {}).get("name") for d in docs if d.get("kind") == "Service"}
    blobs: list[str] = []
    for d in docs:
        if d.get("kind") == "ConfigMap":
            blobs += [str(x) for x in (d.get("data") or {}).values()]
        if d.get("kind") == "Secret":
            blobs += [str(x) for x in (d.get("stringData") or {}).values()]
            for x in (d.get("data") or {}).values():
                try:
                    blobs.append(b64.b64decode(str(x)).decode(errors="ignore"))
                except Exception:  # noqa: BLE001
                    pass
        for c in ((pod_template(d).get("spec") or {}).get("containers") or []) if d.get("kind") in {"Deployment", "StatefulSet"} else []:
            blobs += [str(e.get("value")) for e in c.get("env") or [] if e.get("value")]
    dangling = sorted({h for b in blobs for h in re.findall(r"(?<![/\w-])styrmin-test-[a-z0-9][a-z0-9-]*[a-z0-9](?=\.|:\d|/|$|\n|\"|'|,)", b, re.M)}
                      - service_names)

    app_version = (a.app_version or str(chart.get("appVersion") or "")).lstrip("v")
    if not re.fullmatch(r"\d+(\.\d+)*", app_version):
        # appVersion such as "latest": take the version from the main image tag when it has one
        tags = [img.rsplit(":", 1)[-1] for d in docs if d.get("kind") in {"Deployment", "StatefulSet"}
                for img in [((pod_template(d).get("spec") or {}).get("containers") or [{}])[0].get("image") or ""]
                if ":" in img.split("/")[-1]]
        found = next((m.group(0) for t in tags for m in [re.search(r"\d+\.\d+(\.\d+)?", t)] if m), None)
        app_version = found or app_version
    nums = re.findall(r"\d+", app_version)
    if len(nums) >= 2:
        supported = f">={nums[0]}.{nums[1]},<{nums[0]}.{int(nums[1]) + 1}"
    elif len(nums) == 1:
        supported = f">={nums[0]},<{int(nums[0]) + 1}"
    else:
        app_version, supported = "TODO", "TODO"

    # ---- components ------------------------------------------------------------------------
    workloads = [d for d in docs if d.get("kind") in {"Deployment", "StatefulSet"} and not is_hook(d)]
    pods_of = {id(w): labels(pod_template(w)) for w in workloads}
    components: dict[str, dict] = {}
    todo_components: list[str] = []
    seen_claims: set = set()
    for w in workloads:
        wl, pl = labels(w), pods_of[id(w)]
        common = {k: v for k, v in wl.items() if pl.get(k) == v and k not in EXCLUDED_LABELS}
        ordered = [k for k in PREFERRED_LABELS if k in common] + sorted(k for k in common if k not in PREFERRED_LABELS)
        selector: dict = {}
        for k in ordered:
            selector[k] = common[k]
            # Styrmin selects workloads by their own labels; Services select pods: unique for both
            if sum(1 for w2 in workloads if matches(selector, pods_of[id(w2)])) == 1 \
                    and sum(1 for w2 in workloads if matches(selector, labels(w2))) == 1:
                break
        if not selector:
            todo_components.append(f"{w['kind']}/{w['metadata']['name']}: no label is on both the workload and its "
                                   f"pods; add one with the chart's labels/podLabels values")
            continue
        # Styrmin finds the component's workloads by its first label, and the component container must
        # be in each of them: put first a label whose workloads all have that container, then the
        # most specific one.
        first_container = ((pod_template(w).get("spec") or {}).get("containers") or [{}])[0].get("name")

        def order(kv: tuple[str, str]) -> tuple[int, int]:
            hits = [w2 for w2 in workloads if labels(w2).get(kv[0]) == kv[1]]
            has = all(first_container in [c.get("name") for c in (pod_template(w2).get("spec") or {}).get("containers") or []]
                      for w2 in hits)
            return (0 if has else 1, len(hits))
        selector = dict(sorted(selector.items(), key=order))
        if order(next(iter(selector.items())))[0]:
            others = [f"{w2['kind']}/{w2['metadata']['name']}" for w2 in workloads if w2 is not w
                      and labels(w2).get(next(iter(selector))) == next(iter(selector.values()))]
            todo_components.append(f"{w['kind']}/{w['metadata']['name']}: its labels are also on {', '.join(others)}, "
                                   f"which has no container {first_container!r}, and Styrmin finds a component's "
                                   f"workloads by its first label. Add a label with the chart's labels/podLabels "
                                   f"values. If the chart has none, Styrmin cannot tell these workloads apart: say so in the README")
        comp_label = pl.get("app.kubernetes.io/component") or pl.get("component")
        name_label = pl.get("app.kubernetes.io/name") or pl.get("app")
        if name_label and name_label != chart_name and (not comp_label or comp_label in GENERIC_COMPONENTS):
            cname = name_label
        elif comp_label and comp_label != chart_name:
            cname = comp_label
        else:
            cname = "server"
        cname = re.sub(r"[^a-z0-9-]+", "-", cname.lower()).strip("-") or "server"
        if cname in components and comp_label and comp_label not in cname:
            cname = re.sub(r"[^a-z0-9-]+", "-", f"{cname}-{comp_label}".lower())
        while cname in components:
            cname += "-2"
        tpl = pod_template(w)
        spec = tpl.get("spec") or {}
        containers = spec.get("containers") or []
        image = (containers[0].get("image") if containers else "") or ""
        comp: dict = {"workload": f"{w['kind']}/{w['metadata']['name']}", "selector": selector,
                      "container": containers[0]["name"] if containers else None,
                      "singleton": w["kind"] == "StatefulSet", "image": image, "backup": None,
                      "ports": [pt.get("containerPort") for c in containers for pt in c.get("ports") or []],
                      "port_names": {pt.get("name"): pt.get("containerPort") for c in containers for pt in c.get("ports") or []},
                      "pod_labels": pl}
        kind = next((k for needle, k in BACKUP_BY_IMAGE if needle in image.lower()), None)
        pvc_vols = [v["name"] for v in spec.get("volumes") or [] if "persistentVolumeClaim" in v
                    and v["persistentVolumeClaim"].get("claimName") not in seen_claims]
        seen_claims.update(v["persistentVolumeClaim"].get("claimName") for v in spec.get("volumes") or []
                           if "persistentVolumeClaim" in v)
        pvc_vols += [(t.get("metadata") or {}).get("name") for t in (w.get("spec") or {}).get("volumeClaimTemplates") or []]
        if kind:
            comp["backup"] = {"enabled": True, "kind": kind}
        elif pvc_vols and not any(c in image.lower() for c in CACHE_IMAGES):
            comp["backup"] = {"enabled": True, "kind": "disk", "volumes": pvc_vols}
        comp["kubectl_init"] = [c["name"] for c in spec.get("initContainers") or []
                                if "kubectl" in (c.get("image") or "") or "kubectl" in " ".join(map(str, (c.get("command") or []) + (c.get("args") or [])))]
        comp["api_sidecars"] = [c["name"] for c in (spec.get("initContainers") or []) + (spec.get("containers") or [])
                                if re.search(r"k8s-sidecar|kube-webhook-certgen", c.get("image") or "")]
        components[cname] = comp

    # ---- the external service --------------------------------------------------------------
    services = {(d.get("metadata") or {}).get("name"): d for d in docs if d.get("kind") == "Service"}
    target = None
    for ing in (d for d in docs if d.get("kind") == "Ingress"):
        for rule in (ing.get("spec") or {}).get("rules") or []:
            for path in ((rule.get("http") or {}).get("paths")) or []:
                backend = (path.get("backend") or {}).get("service") or {}
                if backend.get("name") in services:
                    target = (services[backend["name"]], backend.get("port") or {})
                    break
    if target is None:
        web_ports = {80, 443, 3000, 3001, 5000, 5678, 8000, 8008, 8065, 8069, 8080, 8081, 8443, 8888, 9000, 9090}
        db_like = re.compile(r"postgres|mysql|maria|mongo|redis|valkey|memcache|rabbitmq|kafka|elastic|minio|neo4j", re.I)
        candidates = []
        for svc in services.values():
            sel = (svc.get("spec") or {}).get("selector") or {}
            pods = [comp for comp in components.values() if sel and matches(sel, comp["pod_labels"])]
            if not pods or any(db_like.search(comp["image"]) for comp in pods):
                continue
            helper = re.search(r"webhook|injector|exporter|metrics|admission|operator|sidecar|csi|agent",
                               f"{(svc.get('metadata') or {}).get('name', '')} {' '.join(c['workload'] for c in pods)}", re.I)
            for sp in (svc.get("spec") or {}).get("ports") or []:
                names = f"{sp.get('name', '')} {sp.get('targetPort', '')}".lower()
                score = (2 if re.search(r"http|web|ui|https", names) else 0) + (1 if sp.get("port") in web_ports else 0) \
                    + (1 if any(comp["pod_labels"].get("app.kubernetes.io/name") == chart_name for comp in pods) else 0) \
                    - (3 if helper else 0)
                candidates.append((score, svc, sp))
        if candidates:
            score, svc, sp = max(candidates, key=lambda c: c[0])
            target = (svc, {"number": sp.get("port")})
    service_component, service_port = None, None
    if target:
        svc, port_ref = target
        selector = (svc.get("spec") or {}).get("selector") or {}
        for cname, comp in components.items():
            if selector and matches(selector, comp["pod_labels"]):
                service_component = cname
                break
        for sp in (svc.get("spec") or {}).get("ports") or []:
            if port_ref.get("number") in (None, sp.get("port")) and (not port_ref.get("name") or port_ref.get("name") == sp.get("name")):
                tp = sp.get("targetPort") or sp.get("port")
                if isinstance(tp, str) and service_component:
                    tp = components[service_component]["port_names"].get(tp)
                service_port = tp
                break
    if service_component is None and components:
        service_component = next(iter(components))
    if service_port is None and service_component:
        service_port = next((pt for pt in components[service_component]["ports"] if pt), None)

    # ---- driver.styrmin.yml ----------------------------------------------------------------
    links = [{"link": "Homepage", "url": chart["home"]}] if str(chart.get("home", "")).startswith("http") else []
    links += [{"link": "Source", "url": s} for s in (chart.get("sources") or [])[:1] if str(s).startswith("http")]
    icon = chart.get("icon") if str(chart.get("icon", "")).startswith("https://") else None
    lines = [
        "---",
        f"# Draft written by scaffold_driver.py from {location} {a.version}. Lines marked TODO need a decision.",
        'apiVersion: "styrmin.io/v1"',
        "kind: ApplicationDriver",
        "metadata:",
        f"  name: {a.driver_name}",
        "spec:",
        '  version: "1"',
        f'  supported_versions: "{supported}"   # TODO check the versions the chart supports',
        f'  default_version: "{app_version}"',
        "  info:",
    ]
    if icon:
        lines.append(f"    icon: {icon}")
    lines.append(f"    description: {yaml.safe_dump(str(chart.get('description', a.driver_name)), width=1000).strip().removesuffix('...').strip()}")
    if links:
        lines.append("    links:")
        for link in links:
            lines += [f"      - link: {link['link']}", f"        url: {link['url']}"]
    lines += ["  helm:", "    main:", f"      location: {location}", f'      version: "{a.version}"', "", "  components:"]
    for cname, comp in components.items():
        lines.append(f"    {cname}:   # {comp['workload']}, image {comp['image']}")
        if comp["container"]:
            lines.append(f"      container: {comp['container']}")
        if comp["singleton"]:
            lines.append("      singleton: true")
        lines += ["      identifier:", "        label:"]
        lines += [f'          {k}: "{v}"' for k, v in comp["selector"].items()]
        if comp["backup"]:
            b = comp["backup"]
            lines += ["      backup:", "        enabled: true", f"        kind: {b['kind']}"]
            if b["kind"] == "disk":
                lines.append(f"        volumes: [{', '.join(b['volumes'])}]")
            else:
                db = None
                for key in sub_values:
                    if key in comp["image"].lower().split("/")[-1] or key in comp["pod_labels"].values():
                        db = get_path(values, f"{key}.auth.database") or get_path(sub_values[key], "auth.database")
                lines.append(f"        database_name: {db}" if db else "        database_name: TODO   # the database the application uses")
    for t in todo_components:
        lines.append(f"    # TODO {t}")
    if service_component:
        lines += ["", "  services:", f"    - name: {a.driver_name}", "      kind: http", "      scope: external",
                  f"      port: {service_port or 'TODO'}   # the port the container listens on",
                  f"      component: {service_component}"]
    (out / "driver.styrmin.yml").write_text("\n".join(lines) + "\n")

    # ---- values.j2.yml ---------------------------------------------------------------------
    sc = '"{{ instance.config.standard_storage.storage_class }}"'
    main_settings: list[tuple[str, str]] = [("fullnameOverride", f"styrmin-{chart_name}")]
    for path in find_paths(values, lambda k, v: k in ("storageClass", "storageClassName") and not isinstance(v, dict)):
        if path.split(".")[0] not in disabled and path.split(".")[0] not in sub_values and "global" not in path.split("."):
            main_settings.append((path, sc))
    main_image = next((comp["image"] for comp in components.values() if comp["image"]), "")
    tag = main_image.rsplit(":", 1)[-1] if ":" in main_image.split("/")[-1] else ""
    tag_line = None
    if isinstance(values.get("image"), dict) and "tag" in values["image"]:
        prefix = "v" if tag.startswith("v") else ""
        main_settings.append(("image.tag", f'"{prefix}{{{{ app.version }}}}"'))
        tag_line = f"# Image tag: the chart's default image is {main_image}; check the tag format."
    sub_settings: dict[str, list[tuple[str, str]]] = {}
    for key, sv in sub_values.items():
        settings = [("fullnameOverride", sub_fullname(key))]
        settings += [(k.split(".", 1)[1], val) for k, val in user_sets if k.split(".")[0] == key and "." in k]
        for path in find_paths(sv, lambda k, v: k in ("storageClass", "storageClassName") and not isinstance(v, dict)):
            if "global" not in path.split("."):
                settings.append((path, sc))
        sub_settings[key] = settings

    policy_key = None
    for k in EXTRA_OBJECT_KEYS:
        if k in values:
            policy_key = (None, k)
            break
    if policy_key is None:
        for key, sv in sub_values.items():
            if "extraDeploy" in (sv or {}):
                policy_key = (key, "extraDeploy")
                break

    skip_roots = set(disabled) | set(sub_values)  # subchart settings are listed from their own values
    credentials = [c for c in find_paths(values, is_credential) if c.split(".")[0] not in skip_roots]
    credentials += find_paths(values, lambda k, v: k == "apiTokenPeppers")
    for key, sv in sub_values.items():
        credentials += [f"{key}.{p}" for p in find_paths(sv.get("auth") or {}, is_credential, "auth")]
    credentials = list(dict.fromkeys(credentials))

    v: list[str] = [
        f"# Draft written by scaffold_driver.py from {location} {a.version}.",
        "# Lines marked TODO need a decision. Keys come from the chart's values.yaml: check each one.",
    ]
    if tag_line:
        v.append(tag_line)
    if user_sets:
        main_settings += [(k, val) for k, val in user_sets if k.split(".")[0] not in sub_values]
    ingress_values = values.get("ingress") if isinstance(values.get("ingress"), dict) else None
    ingress_sample = (ingress_values or {}).get("hosts") or []
    dict_hosts = bool(ingress_values is not None and "enabled" in ingress_values and ingress_sample
                      and isinstance(ingress_sample[0], dict) and "host" in ingress_sample[0])
    ingress_settings, ingress_note = ([], "") if dict_hosts else discover_ingress(values, base, a.driver_name)
    main_settings += [(k, val) for k, val in ingress_settings if k.split(".")[0] not in sub_values]
    if ingress_note:
        v.append(ingress_note)
    def service_for(suffix: str) -> str:
        """The Service the driver's names give to what the chart calls `<release>-<suffix>`."""
        sub = next((k for k in sub_values if suffix == k or suffix.startswith(f"{k}-")), None)
        return next((n for n in sorted(x for x in service_names if x) if n == f"styrmin-{suffix}" or n.endswith(f"-{suffix}")),
                    sub_fullname(sub) + suffix[len(sub):] if sub else f"styrmin-{suffix}")

    # Values that hold a host built from the release name ("{{ .Release.Name }}-postgresql"): set the
    # Service name instead, so the application finds the subchart under its fullnameOverride.
    release_fixed: dict[str, list[str]] = {}
    for host in dangling:
        suffix = host[len("styrmin-test-"):]
        if any(suffix == k or suffix.startswith(f"{k}-") for k in disabled):
            continue
        paths = [pth for pth in find_paths(values, lambda k, val, sfx=suffix: isinstance(val, str) and ".Release.Name" in val
                                           and val.strip().endswith(f"-{sfx}"))
                 if pth.split(".")[0] not in skip_roots]
        if paths:
            main_settings += [(pth, f'"{service_for(suffix)}"') for pth in paths]
            release_fixed[host] = paths

    own_np: list[str] = []
    if policy_key is None:
        own_np = [pth for pth in find_paths(values, lambda k, val: k.lower() == "networkpolicy" and isinstance(val, dict))
                  if isinstance(get_path(values, pth).get("enabled"), bool) and pth.split(".")[0] not in skip_roots]
        egress_rules = json.dumps(yaml.safe_load(POLICY.format(name="x"))[0]["spec"]["egress"])
        for pth in own_np:
            main_settings.append((f"{pth}.enabled", "true"))
            if isinstance(get_path(values, pth).get("egress"), list):
                main_settings.append((f"{pth}.egress", egress_rules))
        if own_np:
            v += ["# This chart has no value for extra objects (extraDeploy, extraObjects), so the driver cannot add",
                  "# its own egress NetworkPolicy. The chart's NetworkPolicy is on instead (with the egress rules the",
                  "# driver needs, when the chart takes a list): a policy only adds allowed connections.",
                  "# check_driver.py says whether every pod reaches DNS; if one does not: for a single-container",
                  "# application, start again from examples/app-template/; otherwise say in the README that this",
                  "# chart cannot run under Styrmin (\"When no value can carry the policy\" in references/networking.md)."]
    v.append(nested(main_settings))
    v += ["",
          "# TODO credentials: give each of these a fixed value (never generated), or remove the line",
          "# when the application does not use it. Keep the database password the same in the",
          "# application settings and in the database subchart."]
    v += [f"#   {c}" for c in credentials[:40]] or ["#   (no password or secret key found in values.yaml)"]
    v += ["",
          "# TODO first run: find in the application's documentation (its Docker or Kubernetes installation",
          "# page) what a user sees on the first visit: a setup wizard, a database choice, an admin to create.",
          "# Answer with its settings (environment variables, config file) what the configuration can answer,",
          "# so the URL opens a working application, and write the rest in the README (rule 22). Do not assume",
          "# the chart's defaults answer it: read the documentation, and name the page in the README."]
    hosts_expr = [f"{{{{ services['{a.driver_name}'].primary_fqdn }}}}",
                  f"{{{{ services['{a.driver_name}'].human_readable_fqdn }}}}"]
    ingress = values.get("ingress") if isinstance(values.get("ingress"), dict) else None
    sample = (ingress or {}).get("hosts") or []
    if dict_hosts:
        import copy

        class NoAliases(yaml.SafeDumper):
            def ignore_aliases(self, data):  # noqa: ANN001, ANN201
                return True

        entries = []
        for i, _ in enumerate(hosts_expr):
            entry = copy.deepcopy(sample[0])
            entry["host"] = f"__STYRMIN_HOST_{i}__"
            entries.append(entry)
        block = yaml.dump({"ingress": {"enabled": True, "hosts": entries}}, Dumper=NoAliases, sort_keys=False, width=1000)
        for i, h in enumerate(hosts_expr):
            block = block.replace(f"__STYRMIN_HOST_{i}__", f'"{h}"')
        v += ["", "# Ingress: the chart's own host format, with the two hosts Styrmin gives the service.",
              "# Do not set the ingress class: Styrmin sets it.", block.rstrip(),
              "# TODO give these hosts to the application when it checks its host name (allowed hosts,",
              "# CSRF trusted origins, base URL)."]
    elif not ingress_settings:
        v += ["",
              "# TODO ingress: enable the chart's Ingress with these two hosts, in the format of the",
              "# chart's `ingress` values (see values.yaml); each host needs its paths. Do not set the ingress class.",
              *[f"#   \"{h}\"" for h in hosts_expr],
              "# Also give these hosts to the application when it checks its host name (allowed hosts,",
              "# CSRF trusted origins, base URL)."]
    wait_switches = [path for path in find_paths(values, lambda k, val: "wait" in k.lower() and isinstance(val, dict)
                                                 and "enabled" in val)]
    for cname, comp in components.items():
        if comp["kubectl_init"]:
            if wait_switches:
                v.append(f"# Component {cname}: init container(s) {comp['kubectl_init']} call the Kubernetes API, which "
                         "Styrmin's network policies block, so they are turned off here.")
                v.append(nested([(f"{p}.enabled", "false") for p in wait_switches]))
                wait_switches = []
            else:
                v.append(f"# TODO component {cname}: init container(s) {comp['kubectl_init']} call the Kubernetes API, which "
                         "Styrmin's network policies block: turn them off with the chart's values.")
    images = sorted({c.get("image") for w in workloads for c in (pod_template(w).get("spec") or {}).get("containers") or []})
    sidecar_switches = find_paths(values, lambda k, val: isinstance(val, dict) and "enabled" in val
                                  and bool(re.search(r"sidecar|reload", k, re.I)))
    for cname, comp in components.items():
        if comp.get("api_sidecars"):
            v.append(f"# TODO component {cname}: container(s) {comp['api_sidecars']} watch the Kubernetes API, which "
                     "Styrmin's network policies block, so they never become ready. Turn them off; candidate values: "
                     + (", ".join(f"{p}.enabled" for p in sidecar_switches[:6]) or "none found, read values.yaml")
                     + ". Check what the sidecar delivered (for example configuration files) still arrives without it.")
    # Workloads that exist to work on the Kubernetes API (webhooks, injectors, operators): Styrmin's
    # network policies block the API, and users rarely need them in a deployment.
    bound = {(sub.get("name")) for d in docs if d.get("kind") in {"RoleBinding", "ClusterRoleBinding"}
             for sub in d.get("subjects") or [] if sub.get("kind") == "ServiceAccount"}
    switches = sorted(find_paths(values, lambda k, val: isinstance(val, dict) and "enabled" in val
                                 and not isinstance(val["enabled"], (dict, list))), key=lambda pth: pth.count("."))
    for cname, comp in components.items():
        w = next(w for w in workloads if f"{w['kind']}/{w['metadata']['name']}" == comp["workload"])
        sa = (pod_template(w).get("spec") or {}).get("serviceAccountName")
        if sa in bound and re.search(r"webhook|injector|operator|admission|controller-manager", comp["workload"], re.I) \
                and cname != service_component:
            words = set(re.split(r"[-/]", comp["workload"].lower()))
            cands = [pth for pth in switches if pth.split(".")[-1].lower() in words]
            v.append(f"# TODO component {cname}: {comp['workload']} works on the Kubernetes API (its service account "
                     "has a role), which Styrmin's network policies block. Turn it off unless users need it; "
                     "candidate values: " + (", ".join(f"{pth}.enabled" for pth in cands[:4]) or "read values.yaml")
                     + ". Then remove the component from driver.styrmin.yml.")
    bitnami = [i for i in images if re.match(r"^(docker\.io/|registry-1\.docker\.io/)?bitnami/", i or "")]
    for image in bitnami:
        name = image.split("/")[-1].split(":")[0]
        tag = image.split(":")[-1] if ":" in image.split("/")[-1] else "latest"
        legacy = newest_legacy_tag(name)
        pin = f"docker.io/bitnamilegacy/{name}:{legacy}" if legacy else "no bitnamilegacy tag found"
        if tag == "latest":
            v.append(f"# Image {image}: Bitnami publishes only `latest` under docker.io/bitnami; it exists but moves. "
                     f"Keep it, or pin {pin} (an older release) in that subchart's image values.")
        else:
            v.append(f"# TODO image {image}: Bitnami removed versioned tags from docker.io/bitnami, so this tag does not "
                     f"exist. Use {pin}, or `latest`, in that subchart's image values.")
    for key, settings in sub_settings.items():
        dump_backup = bool(components) and any(
            c["backup"] and c["backup"]["kind"] != "disk"
            and (key in c["image"].lower().split("/")[-1] or key in c["pod_labels"].values())
            for c in components.values())
        sv = sub_values.get(key) or {}
        base_path = next((sec for sec in ("primary", "postgresql", "mariadb", "mongodb")
                          if isinstance(sv.get(sec), dict) and isinstance(sv[sec].get("extraVolumes"), list)),
                         "" if isinstance(sv.get("extraVolumes"), list) else None) if dump_backup else None
        # The backup volume goes under the same `<base_path>:` key as the other settings of that
        # section: YAML keeps only the last of two equal keys, so a second block would drop the first.
        section = [(pth[len(base_path) + 1:], val) for pth, val in settings if pth.startswith(f"{base_path}.")] \
            if base_path else []
        if section:
            settings = [(pth, val) for pth, val in settings if not pth.startswith(f"{base_path}.")]
        v += ["", f"{key}:", nested(settings, 2)]
        if policy_key == (key, "extraDeploy"):
            v.append("  # Styrmin denies all egress in the deployment namespace: this policy allows it for every pod.")
            v.append("  extraDeploy:")
            v.append("\n".join("    " + line for line in POLICY.format(name=a.driver_name).splitlines()))
        if dump_backup:
            if base_path is not None:
                pad = "  " + ("  " if base_path else "")
                v.append("  # The dump backup writes to a volume named `backup` mounted at /backup.")
                if base_path:
                    v.append(f"  {base_path}:")
                    if section:
                        v.append(nested(section, 4))
                # Helm replaces lists: keep the entries the chart already sets (the parent chart's
                # values for this subchart win over the subchart's own).
                parent_value = values.get(key)
                parent = parent_value if isinstance(parent_value, dict) else {}
                parent_sec = (parent.get(base_path) or {}) if base_path else parent
                own_sec = (sv.get(base_path) or {}) if base_path else sv
                for list_key, extra in (("extraVolumes", [f"{pad}  - name: backup", f"{pad}    emptyDir: {{}}"]),
                                        ("extraVolumeMounts", [f"{pad}  - name: backup", f"{pad}    mountPath: /backup"])):
                    existing = parent_sec.get(list_key) if isinstance(parent_sec.get(list_key), list) else own_sec.get(list_key)
                    v.append(f"{pad}{list_key}:")
                    if existing:
                        v.append(f"{pad}  # the chart's own entries, kept: a list value replaces the default list")
                        v += [f"{pad}  - {json.dumps(item)}" for item in existing]
                    v += extra
            else:
                v.append("  # TODO backup: the dump strategy needs an emptyDir volume named `backup` mounted at /backup")
                v.append("  # in the database container.")
    for key in sub_values:
        for suffix in ("-ha", "-cluster"):
            if key.endswith(suffix) and key[: -len(suffix)] in disabled:
                simple = key[: -len(suffix)]
                v += ["", f"# TODO architecture: the chart enables `{key}` by default. For one deployment, the simpler",
                      f"# `{simple}` subchart is usually enough. To switch, run the scaffold again with",
                      f"#   --force --set {key}.enabled=false --set {simple}.enabled=true",
                      "# (add the other --set options you used), then check again."]
    for host in dangling:
        suffix = host[len("styrmin-test-"):]
        off = next((k for k in disabled if suffix == k or suffix.startswith(f"{k}-")), None)
        if off:
            v += ["", f"# TODO database: the application connects to `<release>-{suffix}`, the {off} subchart, but the",
                  "# chart leaves that subchart off. Run the scaffold again with",
                  f"#   --force --set {off}.enabled=true",
                  "# (add the other --set options you used), or give the application a database outside the chart."]
            continue
        sub = next((k for k in sub_values if suffix.startswith(k)), None)
        target = service_for(suffix)
        if host in release_fixed:
            v += ["", f"# Host: the chart builds `<release>-{suffix}` in {', '.join(release_fixed[host])}; it is set above to",
                  f"# the Service `{target}`, the name the fullnameOverride gives it."]
            continue
        v += ["", f"# TODO host: the chart builds the host `<release>-{suffix}` from the release name, but with",
              f"# {'the ' + sub + ' subchart' if sub else 'the main chart'}'s fullnameOverride the Service is `{target}`: "
              "the application would not find it.",
              f"# Find where the chart sets it: grep -rn -- '-{suffix}' <pulled chart>/templates/_helpers.tpl",
              "# Then set that host explicitly in the application's settings, if the chart keeps a value you set;",
              "# or turn the subchart off when the application can run without it. Do not remove the",
              "# fullnameOverride: with the 44-character release name, names pass the length limits."]
    if policy_key and policy_key[0] is None:
        v += ["", "# Styrmin denies all egress in the deployment namespace: this policy allows it for every pod.",
              f"{policy_key[1]}:", POLICY.format(name=a.driver_name).rstrip()]
    elif policy_key is None and not own_np:
        v += ["", "# TODO network: this chart has no value for extra objects (extraDeploy, extraObjects) and no",
              "# NetworkPolicy values, so the driver cannot add the egress NetworkPolicy, and without it no pod",
              "# can resolve DNS. For a single-container application, start again from examples/app-template/",
              "# (the bjw-s app-template chart renders NetworkPolicies). Otherwise say in the README that this",
              "# chart cannot run under Styrmin. See \"When no value can carry the policy\" in references/networking.md."]
    (out / "values.j2.yml").write_text(escape_chart_jinja("\n".join(v) + "\n"))

    readme = f"""# {a.driver_name} driver for Styrmin

TODO: one paragraph: what the driver deploys.

| Component | Workload | Backup |
|---|---|---|
""" + "\n".join(f"| `{n}` | {c['workload']} | {c['backup']['kind'] if c['backup'] else 'none'} |" for n, c in components.items()) + f"""

- Chart: `{location}` {a.version} (application {app_version}).
- Credentials: TODO list the default users and passwords, and how to change them.
- Parameters: TODO, or "none".
- Decisions: TODO each choice you made and why.
- Checked: TODO the result of check_driver.py.
- Not verified: TODO, for example "not deployed on a cluster".
"""
    (out / "README.md").write_text(readme)
    print(f"Wrote {out}/driver.styrmin.yml, values.j2.yml and README.md.")
    listed = ", ".join(f"{n} ({c['workload']})" for n, c in components.items())
    print(f"Components: {listed}")
    print(f"External service: {a.driver_name} -> component {service_component}, port {service_port}")
    where = ('.'.join(x for x in policy_key if x) if policy_key else
             f"the chart's own {', '.join(own_np)} (check_driver.py says whether it is enough)" if own_np else
             "NOT PLACED (see TODO network)")
    print(f"NetworkPolicy in: {where}")
    if disabled:
        print(f"Subcharts disabled by default, left out: {', '.join(disabled)}")
    todo_count = sum(f.read_text().count("TODO") for f in (out / "driver.styrmin.yml", out / "values.j2.yml", out / "README.md"))
    print(f"{todo_count} TODO lines to resolve. Next: grep -n TODO {out}/*, fix them, then run check_driver.py.")


if __name__ == "__main__":
    main()
