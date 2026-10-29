#!/usr/bin/env python3
# RUN THIS SCRIPT, DO NOT READ IT: its output says what to fix. `--help` shows the options.
# `--list-checks` prints what it checks.
"""Offline checks for a Styrmin application driver.

Runs the checks that catch the usual reasons a driver fails to load or deploy, without a
Styrmin server or a Kubernetes cluster:

  1. driver.styrmin.yml against the rules of Styrmin's driver loader (v0.1.54)
  2. values.j2.yml rendered with a context shaped like the one Styrmin builds, with no key
     set twice in one mapping (YAML keeps only the last one)
  3. `helm template` of the chart with the rendered values (needs `helm` on PATH)
  4. the rendered manifests against the driver: components (selected by their first label
     only, as Styrmin does), containers, services, ingress hosts, resource names, and the
     network policies Styrmin adds to every deployment namespace (default-deny egress)
  5. actions.py, when the driver declares actions
  6. with --check-images: every container image exists in its registry for linux/amd64
     and linux/arm64 (needs internet access)

Usage:
  python3 check_driver.py <driver-dir> [--app-version 1.2.3] [--param name=value ...]
                          [--check-images] [--keep <dir>]

Exit code: 0 when no check FAILs, 1 when at least one FAILs, 2 on a usage error.
Requirements: Python 3.10+, PyYAML, Jinja2, packaging (pip install pyyaml jinja2 packaging).
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

try:
    import jinja2
    from jinja2.exceptions import SecurityError
    from jinja2.sandbox import SandboxedEnvironment
    import yaml
except ImportError:  # pragma: no cover
    print('FAIL: install the requirements first: pip install pyyaml "jinja2>=3.1.6" packaging')
    sys.exit(2)

# Jinja2 before 3.1.6 lets a template escape the sandbox (CVE-2025-27516), and the sandbox is what
# stops chart text in values.j2.yml from running code on this machine.
if tuple(int(x) for x in re.findall(r"\d+", jinja2.__version__)[:3]) < (3, 1, 6):
    print(f'FAIL: Jinja2 {jinja2.__version__} is too old: pip install "jinja2>=3.1.6"')
    sys.exit(2)

try:
    from packaging.specifiers import InvalidSpecifier, SpecifierSet
    from packaging.version import InvalidVersion, Version
except ImportError:  # pragma: no cover
    SpecifierSet = None  # ty: ignore[invalid-assignment]

# ---------------------------------------------------------------------------------------------
# Reporting

RESULTS: list[tuple[str, str, str]] = []


def report(level: str, section: str, message: str) -> None:
    RESULTS.append((level, section, message))
    print(f"{level:4} [{section}] {message}")


def fail(section: str, message: str) -> None:
    report("FAIL", section, message)


def warn(section: str, message: str) -> None:
    report("WARN", section, message)


def ok(section: str, message: str) -> None:
    report("OK", section, message)


def info(section: str, message: str) -> None:
    report("INFO", section, message)


# ---------------------------------------------------------------------------------------------
# 1. Specification

DNS_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
CONTAINER_NAME = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")
ACTION_LOCATION = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*\.py::[a-z_][a-zA-Z0-9_]+$")
ENV_VAR_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SECRET_NAME = re.compile(r"^[a-z0-9][a-z0-9.-]*[a-z0-9]$")
SPEC_KEYS = {
    "version", "supported_versions", "default_version", "info", "helm", "components",
    "parameters", "services", "actions", "env_vars",
}
BACKUP_KINDS = {"disk", "mariadb", "mongodb", "postgres", "neo4j", "action"}
BACKUP_KEYS = {"enabled", "kind", "volume", "volumes", "database_name", "credentials_secret"}
PARAMETER_KINDS = {"string", "integer", "boolean", "enum"}
SERVICE_KINDS = {"http", "https", "tcp", "udp"}
SERVICE_SCOPES = {"internal", "external"}
MAX_REPLICAS = 2147483647


def is_str(value: Any) -> bool:
    return isinstance(value, str)


BOOL_STRINGS = {"0", "off", "f", "false", "n", "no", "1", "on", "t", "true", "y", "yes"}


def is_bool_like(value: Any) -> bool:
    """Whether the loader (Pydantic) accepts the value for a bool field."""
    if isinstance(value, str):
        return value.strip().lower() in BOOL_STRINGS
    return isinstance(value, bool) or (isinstance(value, int) and value in (0, 1))


def as_bool(value: Any) -> bool:
    """The value of a bool field as the loader (Pydantic) reads it: the string "false" is false."""
    if isinstance(value, str):
        return value.strip().lower() in {"1", "on", "t", "true", "y", "yes"}
    return bool(value)


def check_spec(doc: Any) -> dict | None:
    s = "spec"
    if not isinstance(doc, dict):
        fail(s, "driver.styrmin.yml is not a YAML mapping")
        return None
    for key in doc:
        if key not in {"apiVersion", "kind", "metadata", "spec"}:
            fail(s, f"unknown top-level key {key!r}: the loader refuses extra keys")
    if doc.get("apiVersion") != "styrmin.io/v1":
        fail(s, f"apiVersion must be \"styrmin.io/v1\", found {doc.get('apiVersion')!r}")
    if doc.get("kind") != "ApplicationDriver":
        fail(s, f"kind must be ApplicationDriver, found {doc.get('kind')!r}")
    meta = doc.get("metadata")
    if not isinstance(meta, dict) or not is_str(meta.get("name")):
        fail(s, "metadata.name is required and must be a string")
    elif not DNS_LABEL.match(meta["name"]):
        warn(s, f"metadata.name {meta['name']!r}: use lowercase letters, digits and '-'")
    for key in meta if isinstance(meta, dict) else []:
        if key != "name":
            fail(s, f"unknown key metadata.{key}: the loader refuses extra keys (metadata has only name)")
    spec = doc.get("spec")
    if not isinstance(spec, dict):
        fail(s, "spec is required and must be a mapping")
        return None

    for key in spec:
        if key not in SPEC_KEYS:
            fail(s, f"unknown key spec.{key}: the loader refuses extra keys "
                    f"(allowed: {', '.join(sorted(SPEC_KEYS))})")

    for key in ("version", "supported_versions"):
        if key not in spec:
            fail(s, f"spec.{key} is required")
        elif not is_str(spec[key]):
            fail(s, f"spec.{key} must be a string: quote it, for example {key}: \"{spec[key]}\"")
    if "default_version" in spec and not is_str(spec["default_version"]):
        fail(s, "spec.default_version must be a quoted string")

    supported = spec.get("supported_versions")
    if is_str(supported) and SpecifierSet is not None:
        try:
            spec_set = SpecifierSet(supported)
        except InvalidSpecifier:
            fail(s, f"spec.supported_versions {supported!r} is not a PEP 440 specifier, "
                    "for example \">=4.1,<4.5\"")
            spec_set = None
        default = spec.get("default_version")
        if spec_set is not None and is_str(default):
            try:
                if Version(default) not in spec_set:
                    fail(s, f"default_version {default!r} is outside supported_versions {supported!r}")
            except InvalidVersion:
                fail(s, f"default_version {default!r} is not a PEP 440 version (no 'v' prefix)")

    if "info" not in spec or not isinstance(spec.get("info"), dict):
        fail(s, "spec.info is required (it can be empty: info: {})")
    else:
        info_block = spec["info"]
        for key in info_block:
            if key not in {"icon", "description", "authors", "license", "links"}:
                fail(s, f"unknown key spec.info.{key}")
        icon = info_block.get("icon")
        if icon is not None and (not is_str(icon) or not icon.startswith("https://")):
            warn(s, "spec.info.icon must be an absolute https URL; Styrmin drops it otherwise")
        authors = info_block.get("authors")
        if authors is not None and (not isinstance(authors, list) or not all(is_str(a) for a in authors)):
            fail(s, "spec.info.authors must be a list of strings, for example [opsmill]")
        for key in ("description", "license"):
            if info_block.get(key) is not None and not is_str(info_block[key]):
                fail(s, f"spec.info.{key} must be a string")
        for i, link in enumerate(info_block.get("links") or []):
            if not isinstance(link, dict) or set(link) != {"link", "url"}:
                warn(s, f"spec.info.links[{i}] must have exactly the keys link and url")

    helm = spec.get("helm")
    main = helm.get("main") if isinstance(helm, dict) else None
    for key in helm if isinstance(helm, dict) else []:
        if key != "main":
            fail(s, f"unknown key spec.helm.{key}: the loader refuses extra keys (helm has only main)")
    if not isinstance(main, dict):
        fail(s, "spec.helm.main is required with location and version")
    else:
        for key in main:
            if key not in {"location", "version"}:
                fail(s, f"unknown key spec.helm.main.{key}: the loader refuses extra keys (location, version)")
        if not is_str(main.get("location")):
            fail(s, "spec.helm.main.location is required: \"<repository URL>/<chart name>\"")
        elif main["location"].endswith((".tgz", ".tar.gz", "index.yaml")):
            fail(s, "spec.helm.main.location is \"<repository URL>/<chart name>\", not a file URL")
        if not is_str(main.get("version")):
            fail(s, "spec.helm.main.version is required and must be a quoted string")

    components = spec.get("components") or {}
    if not isinstance(components, dict):
        fail(s, "spec.components must be a mapping of component name to definition")
        components = {}
    for name, comp in components.items():
        c = f"spec.components.{name}"
        if not isinstance(comp, dict):
            fail(s, f"{c} must be a mapping")
            continue
        label = (comp.get("identifier") or {}).get("label") if isinstance(comp.get("identifier"), dict) else None
        if not isinstance(label, dict) or not label:
            fail(s, f"{c}.identifier.label is required: a mapping of label key to value")
        else:
            for k, v in label.items():
                if not is_str(v):
                    fail(s, f"{c}.identifier.label.{k} must be a string: quote {v!r}")
        container = comp.get("container")
        if container is not None and (not is_str(container) or len(container) > 63
                                      or not CONTAINER_NAME.fullmatch(container)):
            fail(s, f"{c}.container {container!r} is not a valid Kubernetes container name")
        replicas = comp.get("replicas")
        if replicas is not None and (isinstance(replicas, bool) or not isinstance(replicas, int)
                                     or not 1 <= replicas <= MAX_REPLICAS):
            fail(s, f"{c}.replicas must be a whole number from 1 to {MAX_REPLICAS}")
        singleton = comp.get("singleton")
        if singleton is not None and not isinstance(singleton, bool):
            fail(s, f"{c}.singleton must be true or false")
        if singleton is True and isinstance(replicas, int) and replicas > 1:
            fail(s, f"{c}: singleton: true cannot be combined with replicas: {replicas}")
        backup = comp.get("backup")
        if backup is not None:
            if not isinstance(backup, dict):
                fail(s, f"{c}.backup must be a mapping")
            else:
                for k in backup:
                    if k not in BACKUP_KEYS:
                        fail(s, f"{c}.backup.{k} is not a backup key ({', '.join(sorted(BACKUP_KEYS))})")
                enabled, kind = as_bool(backup.get("enabled")), backup.get("kind")
                if not is_bool_like(backup.get("enabled", False)):
                    fail(s, f"{c}.backup.enabled must be true or false")
                if (kind is not None or enabled) and not (is_str(kind) and kind in BACKUP_KINDS):
                    fail(s, f"{c}.backup.kind must be one of {', '.join(sorted(BACKUP_KINDS))} "
                            "(the loader checks it even when the backup is disabled)")
                if enabled and kind == "disk" and not (backup.get("volume") or backup.get("volumes")):
                    fail(s, f"{c}.backup kind disk needs volume or volumes (pod-template volume "
                            "names); without them the backup holds no data")
                if enabled and kind == "action":
                    action_names = {a["name"] for a in spec.get("actions") or []
                                    if isinstance(a, dict) and is_str(a.get("name"))}
                    missing = sorted({"backup", "restore"} - action_names)
                    if missing:
                        fail(s, f"{c}.backup kind action needs actions named {' and '.join(missing)} "
                                "in spec.actions")
                volumes = backup.get("volumes")
                if volumes is not None and (not isinstance(volumes, list) or not all(is_str(x) for x in volumes)):
                    fail(s, f"{c}.backup.volumes must be a list of volume names")
                secret = backup.get("credentials_secret")
                if secret is not None and not (is_str(secret) and SECRET_NAME.match(secret)):
                    fail(s, f"{c}.backup.credentials_secret {secret!r} is not a Kubernetes Secret name")

    parameters = spec.get("parameters")
    if parameters is not None:
        if not isinstance(parameters, list):
            fail(s, "spec.parameters must be a list")
            parameters = []
        names = []
        for i, p in enumerate(parameters):
            c = f"spec.parameters[{i}]"
            if not isinstance(p, dict):
                fail(s, f"{c} must be a mapping")
                continue
            for k in p:
                if k not in {"name", "label", "kind", "default", "values"}:
                    fail(s, f"{c}.{k} is not a parameter key (name, label, kind, default, values)")
            for k in ("name", "label", "kind"):
                if not is_str(p.get(k)):
                    fail(s, f"{c}.{k} is required")
            names.append(p.get("name"))
            kind = p.get("kind")
            if kind not in PARAMETER_KINDS:
                fail(s, f"{c}.kind must be one of {', '.join(sorted(PARAMETER_KINDS))}")
                continue
            if kind == "enum" and not p.get("values"):
                fail(s, f"{c}: kind enum needs a non-empty values list")
            if kind != "enum" and "values" in p:
                fail(s, f"{c}: values is only allowed for kind enum")
            default = p.get("default")
            if default is None:
                warn(s, f"{c} ({p.get('name')}) has no default: every deployment must set it, "
                        "and a later driver version cannot retire it")
            else:
                expected = {"string": str, "integer": int, "boolean": bool, "enum": str}[kind]
                if (kind == "integer" and isinstance(default, bool)) or not isinstance(default, expected):
                    fail(s, f"{c}.default must be a {expected.__name__} for kind {kind}")
                if kind == "enum" and p.get("values") and default not in p["values"]:
                    fail(s, f"{c}.default {default!r} is not in values")
            if is_str(p.get("name")) and re.search(r"replica", p["name"], re.I):
                warn(s, f"{c}: do not declare a replica parameter; set components.<name>.replicas")
        if len(names) != len(set(names)):
            fail(s, "spec.parameters names must be unique")

    services = spec.get("services")
    if services is not None:
        if not isinstance(services, list) or not services:
            fail(s, "spec.services must be a non-empty list when present")
            services = []
        names = []
        for i, svc in enumerate(services):
            c = f"spec.services[{i}]"
            if not isinstance(svc, dict):
                fail(s, f"{c} must be a mapping")
                continue
            for k in svc:
                if k not in {"name", "kind", "scope", "port", "component"}:
                    fail(s, f"{c}.{k} is not a service key (name, kind, scope, port, component)")
            name = svc.get("name")
            names.append(name)
            if not is_str(name) or not DNS_LABEL.match(name):
                fail(s, f"{c}.name must be a DNS label (lowercase letters, digits, '-')")
            if svc.get("kind") not in SERVICE_KINDS:
                fail(s, f"{c}.kind must be one of {', '.join(sorted(SERVICE_KINDS))}")
            if svc.get("scope") not in SERVICE_SCOPES:
                fail(s, f"{c}.scope must be internal or external")
            port = svc.get("port")
            if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
                fail(s, f"{c}.port must be a whole number from 1 to 65535")
            if svc.get("component") not in components:
                fail(s, f"{c}.component {svc.get('component')!r} is not a declared component")
        if len(names) != len(set(names)):
            fail(s, "spec.services names must be unique")

    actions = spec.get("actions") or []
    seen_hooks: set[tuple[str, str]] = set()
    if not isinstance(actions, list):
        fail(s, "spec.actions must be a list")
        actions = []
    for i, a in enumerate(actions):
        c = f"spec.actions[{i}]"
        if not isinstance(a, dict):
            fail(s, f"{c} must be a mapping")
            continue
        for k in a:
            if k not in {"name", "location", "description", "hook", "parameters", "mode", "image"}:
                fail(s, f"{c}.{k} is not an action key")
        for k in ("name", "location", "description", "hook", "mode"):
            if not is_str(a.get(k)):
                fail(s, f"{c}.{k} is required")
        if is_str(a.get("location")) and not ACTION_LOCATION.match(a["location"]):
            fail(s, f"{c}.location must look like \"actions.py::function_name\"")
        if a.get("hook") not in {"setup", "upgrade"}:
            fail(s, f"{c}.hook must be setup or upgrade")
        if a.get("mode") not in {"pre", "core", "post"}:
            fail(s, f"{c}.mode must be pre, core or post")
        if a.get("hook") == "setup" and a.get("mode") == "core":
            warn(s, f"{c}: the setup hook has no core step; use pre or post")
        key = (a.get("hook"), a.get("mode"))
        if key in seen_hooks:
            fail(s, f"{c}: at most one action per hook and mode ({key[0]}/{key[1]})")
        seen_hooks.add(key)

    env_vars = spec.get("env_vars")
    if env_vars is not None:
        if not isinstance(env_vars, list):
            fail(s, "spec.env_vars must be a list")
            env_vars = []
        env_names = []
        for i, e in enumerate(env_vars):
            c = f"spec.env_vars[{i}]"
            if not isinstance(e, dict) or not is_str(e.get("name")) or not ENV_VAR_NAME.match(e["name"]):
                fail(s, f"{c}.name must be a POSIX env var name")
                continue
            env_names.append(e["name"])
            for k in e:
                if k not in {"name", "description", "level", "components"}:
                    fail(s, f"{c}.{k} is not an env_vars key (name, description, level, components)")
            if not is_str(e.get("description")) or e.get("level") is None:
                fail(s, f"{c} needs name, description and level")
                continue
            level, targets = e.get("level"), e.get("components") or []
            if not isinstance(targets, list):
                fail(s, f"{c}.components must be a list of component names")
                targets = []
            if level not in ("deployment", "component"):
                fail(s, f"{c}.level must be deployment or component")
            elif level == "component" and not targets:
                fail(s, f"{c}: level component needs a non-empty components list")
            elif level == "deployment" and targets:
                fail(s, f"{c}: level deployment must not list components")
            for target in targets:
                if not is_str(target) or target not in components:
                    fail(s, f"{c}.components: {target!r} is not a declared component")
        if len(env_names) != len(set(env_names)):
            fail(s, "spec.env_vars names must be unique")
    return spec


# ---------------------------------------------------------------------------------------------
# 2. Context and values template

DEPLOYMENT_ID = "4c5e7d1a-2b3f-4a6c-9d8e-0f1a2b3c4d5e"
ENVIRONMENT_ID = "9a8b7c6d-5e4f-4a3b-2c1d-0e9f8a7b6c5d"
NAMESPACE = f"styrmin-{DEPLOYMENT_ID}"
FQDN_SUFFIX = "apps.example.com"
ENVIRONMENT_NAME = "staging"


def to_fqdn_label(value: Any) -> str:
    text = re.sub(r"[^a-z0-9-]+", "-", str(value).lower()).strip("-")
    return text[:63].strip("-")


def build_context(spec: dict, driver_name: str, app_version: str, overrides: dict) -> dict:
    """A context shaped like the one Styrmin 0.1.54 embeds in a StyrminDeployment."""
    location = spec["helm"]["main"]["location"].rstrip("/")
    parameters = {p["name"]: p.get("default") for p in spec.get("parameters") or [] if isinstance(p, dict)}
    parameters.update(overrides)
    resolved_config = {
        "external_url_port": 443,
        "external_url_scheme": "https",
        "fast_storage": {"storage_class": "fast-ssd"},
        "fqdn_suffix": FQDN_SUFFIX,
        "ingress_class": "traefik",
        "runtime_class": "default",
        "standard_storage": {"storage_class": "standard-rwo"},
    }
    services: dict[str, Any] = {}
    deployed: list[dict[str, Any]] = []
    for svc in spec.get("services") or []:
        name = svc["name"]
        services[name] = {
            "host": name,
            "human_readable_fqdn": f"{to_fqdn_label(name)}-{ENVIRONMENT_NAME}.{FQDN_SUFFIX}",
            "kind": svc.get("kind"),
            "port": svc.get("port"),
            # Styrmin builds it from the driver name and the deployment id, the same for every service.
            "primary_fqdn": f"{driver_name}-{DEPLOYMENT_ID}.{FQDN_SUFFIX}",
            "url": f"{svc.get('kind')}://{name}:{svc.get('port')}",
        }
        deployed.append({"component": svc.get("component"), "deployment_id": DEPLOYMENT_ID,
                         "kind": svc.get("kind"), "port": svc.get("port"), "resolved_name": name})
    components = {
        name: {"config": comp, "enabled": True, "name": name}
        for name, comp in (spec.get("components") or {}).items()
    } or None
    context = {
        "app": {
            "helm": {
                "chart": {"name": location.split("/")[-1], "version": spec["helm"]["main"]["version"]},
                "repository": {"url": "/".join(location.split("/")[:-1])},
            },
            "name": driver_name,
            "version": app_version,
        },
        "cluster": {"capabilities": {}, "config": dict(resolved_config)},
        "environment": {"capabilities": {"backup": {"velero": {"storage_location": "styrmin-bsl-1"}}},
                        "config": {}, "name": ENVIRONMENT_NAME},
        "deployment": {"config": {}},
        "instance": {
            "config": resolved_config,
            "deployment_id": DEPLOYMENT_ID,
            "id": "1b2c3d4e-5f6a-4b7c-8d9e-0a1b2c3d4e5f",
            "namespace": NAMESPACE,
            "release_reference": NAMESPACE,
        },
        "labels": {"deployment_id": DEPLOYMENT_ID, "environment_id": ENVIRONMENT_ID},
        "parameters": parameters,
        "services": services,
        "deployed_services": deployed,
        "utilities": [{"kind": "ingress"}, {"kind": "service-discovery"}],
    }
    if components:
        context["components"] = components
    return context


UNDEFINED_SEEN: list[str] = []


class RecordingUndefined(jinja2.Undefined):
    """Renders like Styrmin's SilentUndefined (an empty string) and records each use."""

    def _record(self) -> None:
        UNDEFINED_SEEN.append(self._undefined_name or repr(self._undefined_hint or "?"))

    def _fail_with_undefined_error(self, *args: Any, **kwargs: Any) -> str:  # ty: ignore[invalid-method-override]
        self._record()
        return ""

    def __str__(self) -> str:
        self._record()
        return ""

    def __getattr__(self, name: str) -> Any:
        if name.startswith("__"):
            raise AttributeError(name)
        self._record()
        return RecordingUndefined(name=f"{self._undefined_name}.{name}")

    __getitem__ = __getattr__  # type: ignore[assignment]


class CheckSandbox(SandboxedEnvironment):
    """Jinja's sandbox, raising on an unsafe attribute instead of returning an undefined value
    (RecordingUndefined renders undefined values as an empty string)."""

    def unsafe_undefined(self, obj: Any, attribute: str) -> jinja2.Undefined:
        raise SecurityError(f"access to attribute {attribute!r} of a {type(obj).__name__} object is unsafe")


def retired_filter(name: str):
    def _filter(*args: Any, **kwargs: Any) -> str:
        raise jinja2.TemplateRuntimeError(
            f"the {name} filter is retired: Styrmin applies env vars, command and args to the "
            "component container; remove it from the template")
    return _filter


def duplicate_keys(text: str) -> list[str]:
    """Keys that appear twice in one mapping, as "path (line N)". PyYAML keeps the last one."""
    found: list[str] = []

    def walk(node: yaml.Node | None, path: str) -> None:
        if isinstance(node, yaml.MappingNode):
            seen: set[str] = set()
            for key_node, value_node in node.value:
                key = str(key_node.value)
                if key in seen and key != "<<":
                    found.append(f"{path}{key} (line {key_node.start_mark.line + 1})")
                seen.add(key)
                walk(value_node, f"{path}{key}.")
        elif isinstance(node, yaml.SequenceNode):
            for i, item in enumerate(node.value):
                walk(item, f"{path.rstrip('.')}[{i}].")

    walk(yaml.compose(text), "")
    return found


def render_values(template_text: str, context: dict) -> dict | None:
    s = "template"
    # The sandbox stops a template, or chart text copied into it, from running code on this machine.
    env = CheckSandbox(undefined=RecordingUndefined)
    env.filters["to_fqdn_label"] = to_fqdn_label
    env.filters["split"] = lambda value, sep=None: str(value).split(sep)
    for name in ("component_env_vars", "component_command", "component_args"):
        env.filters[name] = retired_filter(name)
    try:
        rendered = env.from_string(template_text).render(context)
    except jinja2.TemplateSyntaxError as e:
        fail(s, f"values.j2.yml line {e.lineno}: Jinja syntax error: {e.message}")
        return None
    except jinja2.TemplateError as e:
        fail(s, f"values.j2.yml: {e}")
        return None
    except Exception as e:  # noqa: BLE001
        fail(s, f"values.j2.yml does not render: {type(e).__name__}: {e}")
        return None
    for name in sorted(set(UNDEFINED_SEEN)):
        fail(s, f"undefined template variable {name!r}: Styrmin renders it as an empty string. "
                "Check the name against the context reference (services keys are the "
                "spec.services names; parameters are the spec.parameters names)")
    try:
        values = yaml.safe_load(rendered)
    except yaml.YAMLError as e:
        fail(s, f"the rendered values are not valid YAML: {e}")
        print("----- rendered values -----\n" + rendered + "\n---------------------------")
        return None
    if values is None:
        values = {}
    if not isinstance(values, dict):
        fail(s, "the rendered values must be a YAML mapping")
        return None
    for key in duplicate_keys(rendered):
        fail(s, f"the rendered values set {key} twice in the same mapping: YAML keeps only the last one, "
                "so the settings of the first are lost. Merge the two blocks")
    ok(s, "values.j2.yml renders to valid YAML")
    RENDERED["values_text"] = rendered
    if "fullnameOverride" not in values and "fullnameOverride" not in (values.get("global") or {}):
        warn(s, "no top-level fullnameOverride: the release name is 44 characters "
                f"({NAMESPACE}), so chart resource names can pass the 63-character limit")
    return values


RENDERED: dict[str, Any] = {}


# ---------------------------------------------------------------------------------------------
# 3. helm template


CHART_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def unsafe_chart_reference(location: str, version: str) -> str | None:
    """Why helm must not get this chart location or version, or None. Each one is a separate helm
    argument, so a value that starts with '-' would be read as a helm flag."""
    if not location.startswith(("oci://", "http://", "https://")):
        return f"helm.main.location {location!r} must be an oci:// or https:// chart location"
    if not location.startswith("oci://") and not CHART_NAME.match(location.rsplit("/", 1)[-1]):
        return f"helm.main.location {location!r} must end with the chart name (letters, digits, '.', '_', '-')"
    if version.startswith("-"):
        return f"helm.main.version {version!r} is not a chart version"
    return None


def chart_defaults(spec: dict, workdir: Path) -> tuple[dict, dict[str, dict]] | None:
    """The chart's default values, and each subchart's (from the pulled chart), keyed by name or alias."""
    location = spec["helm"]["main"]["location"].rstrip("/")
    version = str(spec["helm"]["main"]["version"])
    if unsafe_chart_reference(location, version):
        return None
    ref = [location] if location.startswith("oci://") else [location.rsplit("/", 1)[1], "--repo", location.rsplit("/", 1)[0]]
    pull_dir = workdir / "pulled"
    shutil.rmtree(pull_dir, ignore_errors=True)
    proc = subprocess.run(["helm", "pull", *ref, "--version", version, "--untar", "--untardir", str(pull_dir)],
                          capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        return None
    charts = [p for p in pull_dir.iterdir() if (p / "Chart.yaml").exists()]
    if not charts:
        return None
    root = charts[0]
    main = yaml.safe_load((root / "values.yaml").read_text()) if (root / "values.yaml").exists() else {}
    subs: dict[str, dict] = {}
    refs: set[str] = set()
    pattern = re.compile(r"\.Values\.([A-Za-z0-9_][A-Za-z0-9_.]*)")

    def collect(folder: Path, prefix: str) -> None:
        for f in folder.rglob("*"):
            if f.is_file() and f.suffix in (".yaml", ".yml", ".tpl", ".txt", ""):
                for m in pattern.finditer(f.read_text(errors="ignore")):
                    refs.add(prefix + m.group(1).rstrip("."))
    collect(root / "templates", "")
    for dep in (yaml.safe_load((root / "Chart.yaml").read_text()) or {}).get("dependencies") or []:
        folder = root / "charts" / dep["name"]
        key = dep.get("alias") or dep["name"]
        if (folder / "values.yaml").exists():
            subs[key] = yaml.safe_load((folder / "values.yaml").read_text()) or {}
        if folder.exists():
            collect(folder, f"{key}.")
            if (yaml.safe_load((folder / "Chart.yaml").read_text()) or {}).get("type") == "library":
                collect(folder, "")   # library helpers (fullname, labels) read the calling chart's values
    REFERENCED.clear()
    REFERENCED.update(refs)
    return main or {}, subs


REFERENCED: set[str] = set()


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def all_paths(node: object, prefix: str = "") -> list[str]:
    out: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            out.append(path)
            out += all_paths(v, path)
    return out


def check_unknown_keys(values: dict, defaults: tuple[dict, dict[str, dict]]) -> None:
    """WARN for value keys the chart does not declare: Helm ignores them without an error."""
    main, subs = defaults
    known = all_paths(main) + [f"{name}.{p}" for name, sv in subs.items() for p in all_paths(sv)]

    def walk(node: dict, default: object, prefix: str) -> None:
        for k, v in node.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            if not prefix and k in subs:
                parent = main.get(k)
                sub_default = deep_merge(subs[k], parent if isinstance(parent, dict) else {})
                if isinstance(v, dict):
                    walk(v, sub_default, path)
                continue
            if k == "global" and not prefix:
                continue
            if not isinstance(default, dict) or not default:
                return  # a free-form map ({} by default) or a scalar: anything goes below it
            if k not in default:
                if path in REFERENCED or any(r.startswith(path + ".") for r in REFERENCED):
                    continue  # the templates read it although values.yaml does not declare it
                same = [p for p in known if p.split(".")[-1] == str(k) and p != path][:3]
                hint = f"; the chart has it at: {', '.join(same)}" if same else ""
                warn("values", f"{path} is not a value of the chart: Helm ignores it without an error{hint}")
                continue
            if isinstance(v, dict):
                walk(v, default[k], path)

    walk(values, main, "")


LIST_KEYS_TO_KEEP = re.compile(r"(volumes|volumemounts|env|envvars|envfrom|initcontainers|sidecars)$", re.I)


def check_dropped_defaults(values: dict, defaults: tuple[dict, dict[str, dict]]) -> None:
    """FAIL when the driver sets a list of volumes, mounts or env vars that drops the chart's default
    entries: Helm replaces a list as a whole, it does not merge it."""
    main, subs = defaults

    def name_of(item: Any) -> str:
        return str(item.get("name")) if isinstance(item, dict) and "name" in item else json.dumps(item, sort_keys=True)

    def walk(node: dict, default: object, prefix: str) -> None:
        if not isinstance(default, dict):
            return
        for k, v in node.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            d = default.get(k)
            if not prefix and k in subs:
                parent = main.get(k)
                d = deep_merge(subs[k], parent if isinstance(parent, dict) else {})
            if isinstance(v, dict):
                walk(v, d, path)
            elif isinstance(v, list) and isinstance(d, list) and d and LIST_KEYS_TO_KEEP.search(str(k)):
                kept = {name_of(i) for i in v}
                dropped = [name_of(i) for i in d if name_of(i) not in kept]
                if dropped:
                    fail("values", f"{path} replaces the chart's default list (Helm does not merge lists) and drops "
                                   f"{', '.join(dropped)}: put the chart's default entries in your list too "
                                   f"(see `{path}` in the chart's values.yaml or the parent chart's values)")

    walk(values, main, "")


def helm_template(spec: dict, values: dict, workdir: Path) -> list[dict] | None:
    s = "chart"
    helm = shutil.which("helm")
    if helm is None:
        fail(s, "helm is not on PATH: install helm 3 to check the chart (https://helm.sh/docs/intro/install/)")
        return None
    location = spec["helm"]["main"]["location"].rstrip("/")
    version = str(spec["helm"]["main"]["version"])
    problem = unsafe_chart_reference(location, version)
    if problem:
        fail(s, problem)
        return None
    values_file = workdir / "values.rendered.yaml"
    values_file.write_text(yaml.safe_dump(values, sort_keys=False))
    cmd = [helm, "template", NAMESPACE]
    if location.startswith("oci://"):
        cmd += [location]
    elif location.startswith(("http://", "https://")):
        repo, chart = location.rsplit("/", 1)
        cmd += [chart, "--repo", repo]
    else:
        fail(s, f"helm.main.location {location!r} must be an oci:// or https:// chart location")
        return None
    cmd += ["--version", version, "--namespace", NAMESPACE, "--values", str(values_file),
            "--skip-tests", "--api-versions", "traefik.io/v1alpha1"]
    print("     $ " + " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if proc.returncode != 0:
        fail(s, "helm template failed:\n" + proc.stderr.strip()[-3000:])
        return None
    (workdir / "manifests.yaml").write_text(proc.stdout)
    docs = [d for d in yaml.safe_load_all(proc.stdout) if isinstance(d, dict) and d.get("kind")]
    ok(s, f"helm template rendered {len(docs)} resources from {location} {version}")
    if location.startswith(("http://", "https://")):
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from chart_summary import oci_location_for
        oci = oci_location_for(location, version)
        if oci:
            fail(s, f"the repository index points {location.rsplit('/', 1)[1]} {version} to {oci}: Helm follows it, "
                    "but FluxCD (which Styrmin uses) cannot, and the install never starts (\"unsupported protocol "
                    f"scheme oci\"). Set helm.main.location: {oci}")
    return docs


# ---------------------------------------------------------------------------------------------
# 4. Manifest checks

POD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "CronJob", "ReplicaSet", "Pod"}


def pod_template(obj: dict) -> dict | None:
    kind = obj.get("kind")
    spec = obj.get("spec") or {}
    if kind == "CronJob":
        return ((spec.get("jobTemplate") or {}).get("spec") or {}).get("template")
    if kind == "Pod":
        return {"metadata": obj.get("metadata") or {}, "spec": spec}
    if kind in POD_KINDS:
        return spec.get("template")
    return None


def labels_of(obj: dict | None) -> dict:
    return dict(((obj or {}).get("metadata") or {}).get("labels") or {})


def name_of(obj: dict) -> str:
    return f"{obj.get('kind')}/{(obj.get('metadata') or {}).get('name')}"


def is_hook(obj: dict) -> bool:
    return "helm.sh/hook" in (((obj.get("metadata") or {}).get("annotations")) or {})


def containers_of(template: dict | None, init: bool = False) -> list[dict]:
    spec = (template or {}).get("spec") or {}
    out = list(spec.get("containers") or [])
    if init:
        out += list(spec.get("initContainers") or [])
    return out


def selector_matches(selector: dict | None, labels: dict) -> bool:
    """Kubernetes LabelSelector semantics; an empty selector matches everything."""
    if selector is None:
        return False
    for k, v in (selector.get("matchLabels") or {}).items():
        if labels.get(k) != v:
            return False
    for expr in selector.get("matchExpressions") or []:
        key, op, values = expr.get("key"), expr.get("operator"), expr.get("values") or []
        if op == "In" and labels.get(key) not in values:
            return False
        if op == "NotIn" and key in labels and labels[key] in values:
            return False
        if op == "Exists" and key not in labels:
            return False
        if op == "DoesNotExist" and key in labels:
            return False
    return True


def styrmin_policies(namespace: str) -> list[dict]:
    """The NetworkPolicies Styrmin writes in every deployment namespace (v0.1.54)."""
    return [
        {"name": "default-deny-egress", "spec": {"podSelector": {}, "policyTypes": ["Egress"]}},
        {"name": "allow-egress-to-environment", "spec": {
            "podSelector": {}, "policyTypes": ["Egress"],
            "egress": [{"to": [{"namespaceSelector": {
                "matchLabels": {"styrmin/environment_id": ENVIRONMENT_ID},
                "matchExpressions": [{"key": "kubernetes.io/metadata.name", "operator": "NotIn",
                                      "values": [namespace]}]}}]}]}},
    ]


class Peer:
    def __init__(self, namespace_labels: dict, pod_labels: dict, ports: list[tuple[int, str, str]]):
        self.namespace_labels = namespace_labels
        self.pod_labels = pod_labels
        self.ports = ports  # (port, protocol, port name)


def egress_allowed(src_labels: dict, policies: list[dict], namespace: str, dst: Peer,
                   port: int, protocol: str, port_name: str) -> bool:
    selecting = []
    for pol in policies:
        spec = pol.get("spec") or {}
        types = spec.get("policyTypes") or (["Ingress", "Egress"] if "egress" in spec else ["Ingress"])
        if "Egress" in types and selector_matches(spec.get("podSelector") or {}, src_labels):
            selecting.append(spec)
    if not selecting:
        return True
    own_ns_labels = {"kubernetes.io/metadata.name": namespace, "styrmin/environment_id": ENVIRONMENT_ID,
                     "styrmin/deployment_id": DEPLOYMENT_ID}
    for spec in selecting:
        for rule in spec.get("egress") or []:
            to = rule.get("to")
            peer_ok = not to
            for peer in to or []:
                if "ipBlock" in peer:
                    continue  # Cilium does not apply CIDR rules to pods of the cluster
                ns_sel = peer.get("namespaceSelector")
                pod_sel = peer.get("podSelector")
                if ns_sel is None:
                    ns_match = dst.namespace_labels == own_ns_labels
                else:
                    ns_match = selector_matches(ns_sel, dst.namespace_labels)
                pod_match = True if pod_sel is None else selector_matches(pod_sel, dst.pod_labels)
                if ns_match and pod_match:
                    peer_ok = True
                    break
            if not peer_ok:
                continue
            ports = rule.get("ports")
            if not ports:
                return True
            for p in ports:
                proto = p.get("protocol", "TCP")
                if proto != protocol:
                    continue
                rule_port = p.get("port")
                end = p.get("endPort")
                if rule_port is None:
                    return True
                if isinstance(rule_port, int) and (rule_port == port or (end and rule_port <= port <= end)):
                    return True
                if isinstance(rule_port, str) and rule_port == port_name:
                    return True
    return False


def check_manifests(spec: dict, docs: list[dict]) -> None:
    s = "components"
    workloads = [d for d in docs if d.get("kind") in POD_KINDS]
    managed = [d for d in workloads if d.get("kind") in {"Deployment", "StatefulSet"}]
    components = spec.get("components") or {}

    for d in docs:
        n = (d.get("metadata") or {}).get("name") or ""
        if len(n) > 63:
            fail("names", f"{name_of(d)}: the name has {len(n)} characters, more than 63: set "
                          "fullnameOverride for this chart or subchart")
        elif d.get("kind") == "StatefulSet" and len(n) > 52:
            warn("names", f"{name_of(d)}: a StatefulSet name over 52 characters breaks its pod labels")

    if not components:
        warn(s, "the driver declares no components: Styrmin cannot stop, start, scale or back up "
                "any part of the application")

    matched_by: dict[str, list[str]] = {}
    for cname, comp in components.items():
        label = ((comp.get("identifier") or {}).get("label")) or {}
        if not label:
            continue
        pods = [w for w in workloads if all(labels_of(pod_template(w)).get(k) == v for k, v in label.items())]
        owned = [w for w in managed if all(labels_of(w).get(k) == v for k, v in label.items())]
        if not pods:
            fail(s, f"component {cname!r}: no pod template has the labels {label}. Use labels that "
                    "the rendered chart sets on the pods (see manifests.yaml)")
            continue
        for w in pods:
            if not is_hook(w):
                matched_by.setdefault(name_of(w), []).append(cname)
        names = ", ".join(name_of(w) for w in pods)
        first_key, first_value = next(iter(label.items()))
        targets = [w for w in managed if labels_of(w).get(first_key) == first_value]
        others = [w for w in targets if w not in owned and not is_hook(w)]
        if not owned:
            fail(s, f"component {cname!r}: the pods of {names} match, but no Deployment or "
                    f"StatefulSet has the labels {label} in its own metadata.labels. Styrmin "
                    "selects the workload by its own labels to stop, start, scale and patch it: "
                    "pick labels the chart puts on both, or add them with the chart's "
                    "labels/commonLabels value")
        elif not others:
            ok(s, f"component {cname!r} -> {', '.join(name_of(w) for w in owned)}")
        container = comp.get("container")
        if owned and others:
            fail(s, f"component {cname!r}: Styrmin selects the workloads by the first label only "
                    f"({first_key}={first_value}), which also selects {', '.join(name_of(w) for w in others)}. "
                    "Stopping, starting, scaling or patching the component would act on them too: put "
                    "first a label that only this component's workloads have")
        if container:
            for w in targets:
                names_in = [c.get("name") for c in containers_of(pod_template(w))]
                if container not in names_in:
                    fail(s, f"component {cname!r}: container {container!r} is not in {name_of(w)} "
                            f"(containers: {names_in}); deployments that set an env var, image, "
                            "command or args fail with COMPONENT_CONTAINER_NOT_FOUND")
        else:
            warn(s, f"component {cname!r} declares no container: users cannot set env vars, an "
                    "image override, command or args on it")
        if any(w.get("kind") == "StatefulSet" for w in owned) and not comp.get("singleton") \
                and re.search(r"postgres|mysql|maria|mongo|redis|valkey|neo4j|db|database|cache",
                              cname + json.dumps(label), re.I):
            warn(s, f"component {cname!r} looks like a single-primary data store: set singleton: true")

    for w in managed:
        if is_hook(w):
            continue
        if name_of(w) not in matched_by:
            warn(s, f"{name_of(w)} is not part of any component (labels {labels_of(pod_template(w))})")
        elif len(matched_by[name_of(w)]) > 1:
            warn(s, f"{name_of(w)} matches several components: {matched_by[name_of(w)]}")
        deadline = (w.get("spec") or {}).get("progressDeadlineSeconds")
        if isinstance(deadline, int) and deadline < 270:
            warn(s, f"{name_of(w)}: progressDeadlineSeconds {deadline} < 270 hides the real "
                    "failure reason behind ProgressDeadlineExceeded")

    hooks = [d for d in docs if is_hook(d)]
    for h in hooks:
        ann = (h.get("metadata") or {}).get("annotations") or {}
        info("hooks", f"{name_of(h)} runs as Helm hook {ann.get('helm.sh/hook')}")

    # Services
    s = "services"
    services_by_name = {(d.get("metadata") or {}).get("name"): d for d in docs if d.get("kind") == "Service"}
    ingresses = [d for d in docs if d.get("kind") == "Ingress"]
    ingress_hosts: dict[str, list[dict]] = {}
    for ing in ingresses:
        for rule in (ing.get("spec") or {}).get("rules") or []:
            host = rule.get("host")
            if not host:
                fail(s, f"{name_of(ing)} has a rule without a host: it catches every hostname of "
                        "the ingress controller")
                continue
            ingress_hosts.setdefault(host, []).append(rule)
            for pth in ((rule.get("http") or {}).get("paths")) or []:
                value = pth.get("path")
                if value is None and pth.get("pathType") in ("Prefix", "Exact"):
                    value = ""  # Kubernetes requires a path for these path types
                if value is not None and (not isinstance(value, str) or not value.startswith("/")):
                    fail(s, f"{name_of(ing)} host {host}: path {str(value)[:80]!r} is not an absolute path: "
                            "Kubernetes rejects the Ingress and the install fails. Give the paths in the format "
                            "the chart's ingress template expects (a string like \"/\", or a {path, pathType} entry)")
                if pth.get("pathType") not in (None, "Prefix", "Exact", "ImplementationSpecific"):
                    fail(s, f"{name_of(ing)} host {host}: pathType {pth.get('pathType')!r} is not valid")
            if not ((rule.get("http") or {}).get("paths")):
                fail(s, f"{name_of(ing)} host {host} has no http.paths: Kubernetes rejects the Ingress "
                        "(spec.rules[].http.paths: Required value) and the install fails. Give each host "
                        "its paths in the chart's ingress format (read the chart's ingress template)")
            for path in ((rule.get("http") or {}).get("paths")) or []:
                backend = (path.get("backend") or {}).get("service") or {}
                bname = backend.get("name")
                if bname and bname not in services_by_name:
                    fail(s, f"{name_of(ing)} host {host} sends traffic to Service {bname!r}, which "
                            "the chart does not create")
    for svc in spec.get("services") or []:
        name, comp = svc.get("name"), svc.get("component")
        if name in services_by_name:
            fail(s, f"the chart creates a Service named {name!r}, the name of the driver service "
                    f"{name!r}: Styrmin creates its own Service with that name. Rename one of them")
        label = ((components.get(comp) or {}).get("identifier") or {}).get("label") or {}
        pods = [w for w in workloads if label and
                all(labels_of(pod_template(w)).get(k) == v for k, v in label.items())]
        ports = {p.get("containerPort") for w in pods for c in containers_of(pod_template(w))
                 for p in c.get("ports") or []}
        ports.discard(None)
        if pods and ports and svc.get("port") not in ports:
            warn(s, f"service {name!r}: port {svc.get('port')} is not a containerPort of component "
                    f"{comp!r} (container ports: {sorted(p for p in ports if p)}). Styrmin's service "
                    "sends traffic to this port on the pod: use the port the container listens on")
        if svc.get("scope") == "external":
            primary = RENDERED["context"]["services"][name]["primary_fqdn"]
            if primary not in ingress_hosts:
                fail(s, f"external service {name!r}: no Ingress has the host "
                        f"{{{{ services['{name}'].primary_fqdn }}}} ({primary}); the application URL "
                        "will not answer. Enable the chart's ingress with that host")
            else:
                ok(s, f"external service {name!r} is served on its primary_fqdn")
    if ingresses and not any(svc.get("scope") == "external" for svc in spec.get("services") or []):
        warn(s, "the chart renders an Ingress but no service has scope: external")

    bound = {}
    for d in docs:
        if d.get("kind") in ("RoleBinding", "ClusterRoleBinding"):
            for subj in d.get("subjects") or []:
                if subj.get("kind") == "ServiceAccount":
                    bound[subj.get("name")] = name_of(d)
    for w in workloads:
        tpl_spec = (pod_template(w) or {}).get("spec") or {}
        sa = tpl_spec.get("serviceAccountName")
        if sa in bound and not is_hook(w):
            warn("network", f"{name_of(w)}: its service account {sa!r} gets Kubernetes permissions ({bound[sa]}), "
                            "so a container probably calls the Kubernetes API, which Styrmin's network policies "
                            "block. Find which one (a sidecar or an init container) and turn it off, or say in the "
                            "README why it is not needed")
        for c in containers_of(pod_template(w), init=True):
            text = " ".join(str(x) for x in [c.get("image") or ""] + (c.get("command") or []) + (c.get("args") or []))
            if re.search(r"\bkubectl\b|bitnami/kubectl|k8s-wait-for|k8s-sidecar|kube-webhook-certgen", text):
                fail("network", f"{name_of(w)}: container {c.get('name')!r} calls the Kubernetes API "
                                f"({(c.get('image') or '')}); Styrmin's network policies block it, so it never "
                                "ends. Turn it off with the chart's values (rule 16)")
    check_dangling_hosts(docs)
    check_missing_refs(docs, workloads)
    check_network(docs, workloads)
    check_backup(spec, workloads)
    RENDERED["images"] = sorted({c.get("image") for w in workloads
                                 for c in containers_of(pod_template(w), init=True) if c.get("image")})
    for image in RENDERED["images"]:
        info("images", image)
        if re.match(r"^(docker\.io/)?bitnami/", image) and not image.endswith(":latest"):
            warn("images", f"{image}: Bitnami stopped publishing versioned tags under docker.io/bitnami "
                           "in 2025. Use docker.io/bitnamilegacy/<image> with an existing tag, or "
                           "another image; run with --check-images to verify")


def check_dangling_hosts(docs: list[dict]) -> None:
    """FAIL when the configuration names a host built from the release name that no Service has.

    Some parent charts build a subchart's host from the release name and ignore that subchart's
    fullnameOverride, so the application looks for `<release>-postgresql` while the Service is
    `styrmin-postgresql`: the lookup fails and the pod never starts."""
    import base64 as b64
    services = {(d.get("metadata") or {}).get("name") for d in docs if d.get("kind") == "Service"}
    texts: list[tuple[str, str]] = []
    for d in docs:
        where = name_of(d)
        if d.get("kind") == "ConfigMap":
            texts += [(where, str(v)) for v in (d.get("data") or {}).values()]
        if d.get("kind") == "Secret":
            texts += [(where, str(v)) for v in (d.get("stringData") or {}).values()]
            for v in (d.get("data") or {}).values():
                try:
                    texts.append((where, b64.b64decode(str(v)).decode(errors="ignore")))
                except Exception:  # noqa: BLE001
                    pass
        tpl = pod_template(d)
        for c in containers_of(tpl, init=True) if tpl else []:
            texts += [(where, str(e.get("value"))) for e in c.get("env") or [] if e.get("value")]
            texts += [(where, " ".join(map(str, (c.get("command") or []) + (c.get("args") or []))))]
    # A host: not the end of a label key (".../<name>"), and followed by a DNS dot, a port or a path.
    pattern = re.compile(r"(?<![/\w-])" + re.escape(NAMESPACE) + r"-[a-z0-9][a-z0-9-]*[a-z0-9](?=\.|:\d|/|$|\n|\"|'|,)", re.M)
    reported: set[str] = set()
    for where, text in texts:
        for host in set(pattern.findall(text)):
            if host in services or host in reported:
                continue
            reported.add(host)
            fail("services", f"{where} refers to host {host!r}, but no Service has that name: the application "
                             "cannot connect to it. The chart builds this name from the release name; the "
                             "Service follows your fullnameOverride. Set the host explicitly in the "
                             "application's settings to the Service name, or remove that fullnameOverride "
                             f"(Services: {', '.join(sorted(x for x in services if x))})")


def check_missing_refs(docs: list[dict], workloads: list[dict]) -> None:
    """FAIL when a pod needs a Secret or ConfigMap that the chart does not create: it never starts."""
    made = {(d.get("kind"), (d.get("metadata") or {}).get("name")) for d in docs}
    for w in workloads:
        tpl = pod_template(w) or {}
        spec = tpl.get("spec") or {}
        needed: list[tuple[str, str, bool]] = []
        for c in containers_of(tpl, init=True):
            for e in c.get("env") or []:
                ref = (e.get("valueFrom") or {})
                for key, kind in (("secretKeyRef", "Secret"), ("configMapKeyRef", "ConfigMap")):
                    if ref.get(key):
                        needed.append((kind, ref[key].get("name"), bool(ref[key].get("optional"))))
            for e in c.get("envFrom") or []:
                for key, kind in (("secretRef", "Secret"), ("configMapRef", "ConfigMap")):
                    if e.get(key):
                        needed.append((kind, e[key].get("name"), bool(e[key].get("optional"))))
        for v in spec.get("volumes") or []:
            if v.get("secret"):
                needed.append(("Secret", v["secret"].get("secretName"), bool(v["secret"].get("optional"))))
            if v.get("configMap"):
                needed.append(("ConfigMap", v["configMap"].get("name"), bool(v["configMap"].get("optional"))))
            for src in (v.get("projected") or {}).get("sources") or []:
                for key, kind in (("secret", "Secret"), ("configMap", "ConfigMap")):
                    if src.get(key):
                        needed.append((kind, src[key].get("name"), bool(src[key].get("optional"))))
        for kind, name, optional in dict.fromkeys(needed):
            if name and not optional and (kind, name) not in made:
                fail("components", f"{name_of(w)} needs {kind} {name!r}, which the chart does not create: the pod "
                                   "never starts (CreateContainerConfigError). Set the value that makes the chart "
                                   "create it, or point the setting at a Secret the chart creates")


def check_network(docs: list[dict], workloads: list[dict]) -> None:
    s = "network"
    policies = styrmin_policies(NAMESPACE) + [
        {"name": (d.get("metadata") or {}).get("name"), "spec": d.get("spec") or {}}
        for d in docs if d.get("kind") == "NetworkPolicy"]
    dns = Peer({"kubernetes.io/metadata.name": "kube-system"}, {"k8s-app": "kube-dns"},
               [(53, "UDP", "dns")])
    own_ns = {"kubernetes.io/metadata.name": NAMESPACE, "styrmin/environment_id": ENVIRONMENT_ID,
              "styrmin/deployment_id": DEPLOYMENT_ID}
    peers = []
    for w in workloads:
        tpl = pod_template(w)
        ports = [(p.get("containerPort"), p.get("protocol", "TCP"), p.get("name") or "")
                 for c in containers_of(tpl) for p in c.get("ports") or [] if p.get("containerPort")]
        peers.append((w, Peer(own_ns, labels_of(tpl), ports)))
    all_dns_ok = True
    for w, src in peers:
        if not egress_allowed(src.pod_labels, policies, NAMESPACE, dns, 53, "UDP", "dns"):
            all_dns_ok = False
            fail(s, f"{name_of(w)}: cannot reach DNS (kube-dns, UDP 53). Styrmin denies all egress "
                    "in the deployment namespace: ship a NetworkPolicy that allows it (see "
                    "references/networking.md)")
        blocked = []
        for w2, dst in peers:
            if w2 is w:
                continue
            for port, proto, pname in dst.ports:
                if not egress_allowed(src.pod_labels, policies, NAMESPACE, dst, port, proto, pname):
                    blocked.append(f"{name_of(w2)}:{port}")
        if blocked:
            warn(s, f"{name_of(w)} cannot open connections to {', '.join(blocked)}. If it needs "
                    "them (for example the application to its database or cache), allow egress to "
                    "the pods of its own namespace")
    if all_dns_ok:
        ok(s, "every pod can reach DNS")


def claims_of(pods: list[dict]) -> set:
    return {v["persistentVolumeClaim"].get("claimName") for w in pods
            for v in ((pod_template(w) or {}).get("spec") or {}).get("volumes") or [] if "persistentVolumeClaim" in v}


def check_backup(spec: dict, workloads: list[dict]) -> None:
    s = "backup"
    backed_claims: set = set()
    for comp in (spec.get("components") or {}).values():
        if (comp.get("backup") or {}).get("enabled"):
            label = ((comp.get("identifier") or {}).get("label")) or {}
            backed_claims |= claims_of([w for w in workloads if label and
                                        all(labels_of(pod_template(w)).get(k) == v for k, v in label.items())])
    for cname, comp in (spec.get("components") or {}).items():
        backup = comp.get("backup") or {}
        label = ((comp.get("identifier") or {}).get("label")) or {}
        pods = [w for w in workloads if label and
                all(labels_of(pod_template(w)).get(k) == v for k, v in label.items())]
        has_pvc = any((w.get("spec") or {}).get("volumeClaimTemplates") or
                      any("persistentVolumeClaim" in v for v in ((pod_template(w) or {}).get("spec") or {}).get("volumes") or [])
                      for w in pods)
        if not backup.get("enabled"):
            own_claims = claims_of(pods)
            if own_claims and own_claims <= backed_claims and not any((w.get("spec") or {}).get("volumeClaimTemplates") for w in pods):
                info(s, f"component {cname!r} shares its volumes with a component that backs them up")
            elif has_pvc:
                warn(s, f"component {cname!r} has a persistent volume but no backup block")
            continue
        kind = backup.get("kind")
        if kind in {"postgres", "mariadb", "mongodb", "neo4j"}:
            container = comp.get("container")
            for w in pods:
                tpl_spec = (pod_template(w) or {}).get("spec") or {}
                vols = {v.get("name") for v in tpl_spec.get("volumes") or []}
                if "backup" not in vols:
                    fail(s, f"component {cname!r} ({kind}): {name_of(w)} has no volume named 'backup'. "
                            "The dump strategy writes to a volume named 'backup' mounted at /backup: "
                            "add an emptyDir 'backup' volume and mount it at /backup in the database container")
                    continue
                cont = [c for c in containers_of(pod_template(w)) if not container or c.get("name") == container]
                mounted = any(m.get("name") == "backup" and m.get("mountPath") == "/backup"
                              for c in cont for m in c.get("volumeMounts") or [])
                if not mounted:
                    fail(s, f"component {cname!r} ({kind}): mount the 'backup' volume at /backup in "
                            f"container {container or '(first)'}")
            if kind == "postgres":
                for w in pods:
                    env = {e.get("name") for c in containers_of(pod_template(w)) for e in c.get("env") or []}
                    missing = [n for n in ("POSTGRES_USER", "POSTGRES_DATABASE") if n not in env]
                    if missing and not any(c.get("envFrom") for c in containers_of(pod_template(w))):
                        warn(s, f"component {cname!r}: the pg_dump hook reads POSTGRES_USER, "
                                "POSTGRES_DATABASE and POSTGRES_PASSWORD (or POSTGRES_PASSWORD_FILE) "
                                f"from the container env; {name_of(w)} does not set {missing}")
        ok(s, f"component {cname!r} backup kind {kind}")


# ---------------------------------------------------------------------------------------------
# 5. actions.py

ALLOWED_IMPORT_ROOTS = {"prefect", "styrmin_backend", "styrmin_sdk", "httpx", "pydantic", "yaml"}


def check_actions(spec: dict, driver_dir: Path) -> None:
    s = "actions"
    actions = spec.get("actions") or []
    path = driver_dir / "actions.py"
    if not actions:
        if path.exists():
            warn(s, "actions.py exists but spec.actions declares nothing: Styrmin ignores it")
        return
    if not path.exists():
        fail(s, "spec.actions declares actions but actions.py is missing")
        return
    source = path.read_text()
    try:
        tree = ast.parse(source)
    except SyntaxError as e:
        fail(s, f"actions.py line {e.lineno}: {e.msg}")
        return
    functions = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    local_modules = {p.stem for p in driver_dir.glob("*.py")}
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    for node in ast.walk(tree):
        mods = []
        if isinstance(node, ast.Import):
            mods = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods = [node.module.split(".")[0]]
        for m in mods:
            if m not in ALLOWED_IMPORT_ROOTS and m not in stdlib and m not in local_modules:
                warn(s, f"actions.py imports {m!r}: the Styrmin agent image may not have it")
    components = set((spec.get("components") or {}).keys())
    for a in actions:
        loc = a.get("location") or ""
        if "::" not in loc:
            continue
        file_name, func = loc.split("::", 1)
        if file_name != "actions.py":
            fail(s, f"action {a.get('name')!r}: a driver loaded from a directory must keep actions in "
                    "actions.py")
            continue
        fn = functions.get(func)
        if fn is None:
            fail(s, f"action {a.get('name')!r}: actions.py has no top-level function {func!r}")
            continue
        decorated = any((isinstance(d, ast.Name) and d.id == "flow") or
                        (isinstance(d, ast.Attribute) and d.attr == "flow") or
                        (isinstance(d, ast.Call) and getattr(d.func, "id", getattr(d.func, "attr", "")) == "flow")
                        for d in fn.decorator_list)
        if not decorated:
            fail(s, f"{func}: decorate it with @flow from prefect")
        args = [x.arg for x in fn.args.args]
        if not args or args[0] != "context":
            fail(s, f"{func}: the first parameter must be `context: GlobalContext`")
        if a.get("hook") == "upgrade" and a.get("mode") == "core":
            if "target_version" not in args:
                fail(s, f"{func}: the upgrade core action receives `target_version: str`")
            calls = {getattr(n.func, "id", getattr(n.func, "attr", "")) for n in ast.walk(fn)
                     if isinstance(n, ast.Call)}
            if "upgrade_deployment_version" not in calls:
                fail(s, f"{func}: an upgrade core action replaces Styrmin's upgrade, so it must call "
                        "upgrade_deployment_version(target_version=..., context=context)")
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) in {
                    "stop_components", "start_components"}:
                for kw in n.keywords:
                    if kw.arg == "components" and isinstance(kw.value, ast.List):
                        for elt in kw.value.elts:
                            if isinstance(elt, ast.Constant) and elt.value not in components:
                                fail(s, f"{func}: component {elt.value!r} is not declared in spec.components")
    ok(s, f"actions.py defines {len(actions)} declared action(s)")


# ---------------------------------------------------------------------------------------------
# 6. Images

def _registry_parts(image: str) -> tuple[str, str, str]:
    ref = image
    digest = None
    if "@" in ref:
        ref, digest = ref.split("@", 1)
    first = ref.split("/", 1)[0]
    if "/" in ref and ("." in first or ":" in first or first == "localhost"):
        registry, repo = ref.split("/", 1)
    else:
        registry, repo = "registry-1.docker.io", ref
        if "/" not in repo:
            repo = f"library/{repo}"
    if registry in ("docker.io", "index.docker.io"):
        registry = "registry-1.docker.io"
    if registry == "registry-1.docker.io" and "/" not in repo.split(":")[0]:
        repo = f"library/{repo}"
    tag = "latest"
    if ":" in repo.rsplit("/", 1)[-1]:
        repo, tag = repo.rsplit(":", 1)
    return registry, repo, digest or tag


def _http(url: str, headers: dict) -> tuple[int, dict, bytes]:
    # Some registries refuse Python's default User-Agent (HTTP 403).
    req = urllib.request.Request(url, headers={"User-Agent": "styrmin-driver-check/1.0", **headers})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


def check_image(image: str) -> None:
    s = "images"
    registry, repo, ref = _registry_parts(image)
    accept = ", ".join([
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ])
    url = f"https://{registry}/v2/{repo}/manifests/{ref}"
    headers: dict[str, str] = {"Accept": accept}
    try:
        status, hdrs, body = _http(url, headers)
        if status == 401:
            auth = hdrs.get("www-authenticate") or ""
            params = dict(re.findall(r'(\w+)="([^"]*)"', auth))
            if params.get("realm", "").startswith("https://"):
                token_url = f"{params['realm']}?service={params.get('service', '')}&scope=repository:{repo}:pull"
                _, _, tbody = _http(token_url, {})
                token = json.loads(tbody or b"{}").get("token") or json.loads(tbody or b"{}").get("access_token")
                if token:
                    headers["Authorization"] = f"Bearer {token}"
                    status, hdrs, body = _http(url, headers)
    except Exception as e:  # noqa: BLE001
        warn(s, f"{image}: could not query the registry ({e})")
        return
    if status == 404:
        fail(s, f"{image}: the tag does not exist in {registry}/{repo}")
        return
    if status != 200:
        warn(s, f"{image}: registry answered HTTP {status}; check the image by hand")
        return
    manifest = json.loads(body or b"{}")
    platforms = {f"{m.get('platform', {}).get('os')}/{m.get('platform', {}).get('architecture')}"
                 for m in manifest.get("manifests") or []}
    if not platforms:
        info(s, f"{image}: exists (single-platform image)")
        return
    missing = [p for p in ("linux/amd64", "linux/arm64") if p not in platforms]
    if missing:
        warn(s, f"{image}: exists, but has no {', '.join(missing)} build")
    else:
        ok(s, f"{image}: exists for linux/amd64 and linux/arm64")


# ---------------------------------------------------------------------------------------------


LIST_OF_CHECKS = """\
spec       driver.styrmin.yml against Styrmin's loader: required keys, no unknown keys, quoted
           versions, PEP 440 ranges, default_version in range, component/parameter/service/
           action/backup/env_vars fields (a backup block even when it is disabled)
template   values.j2.yml renders with a realistic context; every undefined variable is a FAIL
           (Styrmin renders it as an empty string); the result is valid YAML with no key set
           twice in one mapping (YAML keeps only the last one); fullnameOverride
values     keys the chart does not declare (Helm ignores them), with where the key exists
chart      helm template of the pinned chart with the rendered values
names      resource names of 63 characters or less
components each component's labels match a workload and its pods; its first label selects no
           other workload (Styrmin selects by the first label only); the container exists in every
           workload its first label selects; singleton data stores; workloads without a component
services   the chart does not create a Service named like a driver service; the service port is a
           container port; an external service has an Ingress with its primary_fqdn and paths
network    every pod can reach DNS under Styrmin's default-deny egress; pods can reach each
           other; no container calls the Kubernetes API
backup     dump strategies have the `backup` volume at /backup and the credentials env;
           volumes without a backup
actions    actions.py functions exist, are Prefect flows, take context; an upgrade core action
           calls upgrade_deployment_version; component names exist
images     (--check-images) every image tag exists, for linux/amd64 and linux/arm64
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    if "--list-checks" in sys.argv:
        print(LIST_OF_CHECKS)
        return 0
    parser.add_argument("driver_dir", type=Path)
    parser.add_argument("--app-version", help="application version to render (default: spec.default_version)")
    parser.add_argument("--param", action="append", default=[], help="parameter value, name=value")
    parser.add_argument("--check-images", action="store_true", help="query registries for every image")
    parser.add_argument("--keep", type=Path, help="write values.rendered.yaml and manifests.yaml here")
    parser.add_argument("--list-checks", action="store_true", help="print what the script checks and exit")
    args = parser.parse_args()

    driver_dir: Path = args.driver_dir
    spec_file = driver_dir / "driver.styrmin.yml"
    if not spec_file.exists():
        print(f"FAIL [spec] {spec_file} does not exist")
        return 1
    try:
        doc = yaml.safe_load(spec_file.read_text())
    except yaml.YAMLError as e:
        print(f"FAIL [spec] driver.styrmin.yml is not valid YAML: {e}")
        return 1
    spec = check_spec(doc)
    if spec is None or any(r[0] == "FAIL" for r in RESULTS):
        print("\nFix the spec FAILs above, then run the check again.")
        return 1
    ok("spec", "driver.styrmin.yml follows the driver schema")

    app_version = args.app_version or spec.get("default_version")
    if not app_version:
        fail("spec", "set spec.default_version, or pass --app-version, to render the template")
        return 1
    overrides: dict[str, Any] = {}
    for item in args.param:
        k, _, v = item.partition("=")
        overrides[k] = int(v) if v.isdigit() else (v.lower() == "true" if v.lower() in {"true", "false"} else v)
    context = build_context(spec, doc["metadata"]["name"], str(app_version), overrides)
    RENDERED["context"] = context

    values: dict | None = {}
    values_file = driver_dir / "values.j2.yml"
    if values_file.exists():
        values = render_values(values_file.read_text(), context)
    else:
        warn("template", "no values.j2.yml: the chart deploys with its defaults")
    workdir = args.keep or Path(tempfile.mkdtemp(prefix="styrmin-driver-check-"))
    workdir.mkdir(parents=True, exist_ok=True)
    if values is not None:
        defaults = chart_defaults(spec, workdir)
        if defaults is not None:
            check_unknown_keys(values, defaults)
            check_dropped_defaults(values, defaults)
        docs = helm_template(spec, values, workdir)
        if docs is not None:
            check_manifests(spec, docs)
            if args.check_images:
                for image in RENDERED.get("images", []):
                    check_image(image)
    check_actions(spec, driver_dir)

    fails = sum(1 for r in RESULTS if r[0] == "FAIL")
    warns = sum(1 for r in RESULTS if r[0] == "WARN")
    print(f"\n{fails} FAIL, {warns} WARN. Rendered files: {workdir}")
    if fails:
        print("Fix every FAIL. Read every WARN and fix it unless you can say why it does not apply.")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
