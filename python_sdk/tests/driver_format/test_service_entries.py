"""Service entries of a context (#598, ADR-0089): ordering, ingress overrides and the context file.

The server and ``styrmin-driver`` both build the ``services`` and ``deployed_services`` entries
with ``build_service_entries``, so these tests run it without the backend.
"""

from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import yaml
from styrmin_sdk.driver_format.context.models.config import ResolvedConfig, ServiceConfigBlock
from styrmin_sdk.driver_format.context.service_entries import build_service_entries, order_deployed_services

from .conftest import EXAMPLES

OWN = UUID("00000000-0000-0000-0000-00000000000a")
PEER_LOW = UUID("00000000-0000-0000-0000-000000000001")
PEER_HIGH = UUID("00000000-0000-0000-0000-000000000002")


@dataclass(frozen=True)
class Row:
    driver_service_name: str
    deployment_id: UUID
    kind: str = "http"
    scope: str = "external"
    resolved_name: str = ""
    port: int = 8000
    component: str = "server"

    def __post_init__(self) -> None:
        if not self.resolved_name:
            object.__setattr__(self, "resolved_name", f"{self.driver_service_name}-svc")


def _config(**values: object) -> ResolvedConfig:
    return ResolvedConfig.model_validate({"ingress_class": "traefik", "fqdn_suffix": "apps.example.org", **values})


def _names(rows: list[Row]) -> list[tuple[UUID, str]]:
    return [(row.deployment_id, row.driver_service_name) for row in rows]


def test_own_services_come_last_in_declared_order_and_peers_come_first_by_id_and_name() -> None:
    rows = [
        Row("zeta", OWN),
        Row("undeclared-b", OWN),
        Row("alpha", OWN),
        Row("undeclared-a", OWN),
        Row("web", PEER_HIGH),
        Row("api", PEER_HIGH),
        Row("web", PEER_LOW),
    ]

    ordered = order_deployed_services(rows, deployment_id=OWN, declared_names=["alpha", "zeta"])

    assert _names(ordered) == [
        (PEER_LOW, "web"),
        (PEER_HIGH, "api"),
        (PEER_HIGH, "web"),
        (OWN, "alpha"),
        (OWN, "zeta"),
        (OWN, "undeclared-a"),
        (OWN, "undeclared-b"),
    ]


def test_the_services_of_this_deployment_win_a_key_that_a_peer_shares() -> None:
    rows = [Row("web", OWN, resolved_name="own-web"), Row("web", PEER_LOW, resolved_name="peer-web")]

    services, deployed, has_own = build_service_entries(
        rows,
        config=_config(),
        service_overrides={},
        declared_names=["web"],
        app_name="app",
        deployment_id=OWN,
        environment_name="env",
    )

    assert services["web"]["host"] == "own-web"
    assert [entry["resolved_name"] for entry in deployed] == ["peer-web", "own-web"]
    assert has_own is True


def test_only_an_external_http_service_takes_the_override_of_its_owner() -> None:
    rows = [
        Row("web", OWN, kind="http", scope="external"),
        Row("admin", OWN, kind="http", scope="internal"),
        Row("queue", OWN, kind="tcp", scope="external", port=5672),
    ]
    override = ServiceConfigBlock(ingress_class="internal-nginx", fqdn_suffix="svc.example.org")

    services, deployed, _has_own = build_service_entries(
        rows,
        config=_config(),
        service_overrides={OWN: {"web": override, "admin": override, "queue": override}},
        declared_names=["web", "admin", "queue"],
        app_name="app",
        deployment_id=OWN,
        environment_name="env",
    )

    assert services["web"]["ingress_class"] == "internal-nginx"
    assert services["web"]["overridden"] is True
    assert services["web"]["human_readable_fqdn"].endswith(".svc.example.org")
    # The application address keeps the resolved suffix.
    assert services["web"]["primary_fqdn"].endswith(".apps.example.org")
    for name in ("admin", "queue"):
        assert services[name]["ingress_class"] == "traefik"
        assert services[name]["overridden"] is False
        assert services[name]["human_readable_fqdn"].endswith(".apps.example.org")
    by_name = {entry["driver_service_name"]: entry for entry in deployed}
    assert by_name["web"]["ingress_class"] == "internal-nginx"
    assert by_name["web"]["fqdn_suffix"] == "svc.example.org"
    assert by_name["web"]["scope"] == "external"
    assert by_name["admin"]["scope"] == "internal"
    assert by_name["queue"]["kind"] == "tcp"


def test_a_service_uses_the_override_of_its_owner_and_never_that_of_this_deployment() -> None:
    peer_id = uuid4()
    rows = [Row("web", peer_id, resolved_name="peer-web"), Row("web", OWN, resolved_name="own-web")]
    own_override = ServiceConfigBlock(ingress_class="own-class")
    peer_override = ServiceConfigBlock(ingress_class="peer-class")

    _services, deployed, _has_own = build_service_entries(
        rows,
        config=_config(),
        service_overrides={OWN: {"web": own_override}, peer_id: {"web": peer_override}},
        declared_names=["web"],
        app_name="app",
        deployment_id=OWN,
        environment_name="env",
    )

    classes = {entry["resolved_name"]: entry["ingress_class"] for entry in deployed}
    assert classes == {"peer-web": "peer-class", "own-web": "own-class"}


def test_an_override_with_one_field_falls_back_to_the_resolved_value_for_the_other() -> None:
    services, deployed, _has_own = build_service_entries(
        [Row("web", OWN)],
        config=_config(),
        service_overrides={OWN: {"web": ServiceConfigBlock(ingress_class="only-class")}},
        declared_names=["web"],
        app_name="app",
        deployment_id=OWN,
        environment_name="env",
    )

    assert services["web"]["ingress_class"] == "only-class"
    assert deployed[0]["fqdn_suffix"] == "apps.example.org"


def test_a_deployment_without_its_own_service_has_no_own_services() -> None:
    _services, _deployed, has_own = build_service_entries(
        [Row("web", PEER_LOW)],
        config=_config(),
        service_overrides={},
        declared_names=[],
        app_name="app",
        deployment_id=OWN,
        environment_name="env",
    )

    assert has_own is False


def test_a_context_file_with_a_service_override_reaches_the_offline_entries(tmp_path: Path, run_cli) -> None:
    context = tmp_path / "ctx.yml"
    context.write_text(
        "deployment:\n"
        "  config:\n"
        "    services:\n"
        "      task-manager:\n"
        "        ingress_class: internal-nginx\n"
        "        fqdn_suffix: svc.example.org\n"
        "      infrahub:\n"
        "        ingress_class: ignored-internal\n",
        encoding="utf-8",
    )

    result = run_cli("context", str(EXAMPLES / "infrahub-enterprise"), "--context", str(context))

    assert result.code == 0, result.err
    services = yaml.safe_load(result.out)["services"]
    assert services["task-manager"]["ingress_class"] == "internal-nginx"
    assert services["task-manager"]["overridden"] is True
    assert services["task-manager"]["human_readable_fqdn"].endswith(".svc.example.org")
    # ``infrahub`` is an internal service: Styrmin builds no Ingress for it, so the override is not applied.
    assert services["infrahub"]["overridden"] is False
    assert services["infrahub"]["ingress_class"] != "ignored-internal"


def test_a_context_file_with_an_invalid_ingress_class_is_refused(tmp_path: Path, run_cli) -> None:
    context = tmp_path / "ctx.yml"
    context.write_text(
        "deployment:\n  config:\n    services:\n      task-manager:\n        ingress_class: Bad_Class\n",
        encoding="utf-8",
    )

    result = run_cli("context", str(EXAMPLES / "infrahub-enterprise"), "--context", str(context))

    assert result.code != 0
    assert "ingress_class" in result.err
