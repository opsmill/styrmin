"""``ServiceConfigBlock`` and ``DeploymentConfig.services``: the stored service ingress override (#598, T007).

Written before the implementation (Constitution V). The planned names come from
``specs/033-service-ingress-override/data-model.md``:

- ``ServiceConfigBlock`` in ``styrmin_backend.context.models.config``, ``extra="forbid"``, two optional
  fields ``ingress_class`` and ``fqdn_suffix``.
- ``DeploymentConfig.services``: ``dict[driver service name, ServiceConfigBlock] | None``.

Every test resolves the planned symbol inside the test, so a missing symbol fails that test with an
``AttributeError`` and does not break the collection of the rest of the suite.

Rejection tests first build a valid control value. Without it they would pass today for the wrong
reason, because ``DeploymentConfig`` already rejects the unknown key ``services``
(``extra="forbid"``).
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest
from pydantic import ValidationError

from styrmin_backend.context.models.config import DeploymentConfig
from styrmin_backend.context.resolvers import resolve_global_context
from styrmin_backend.services.exceptions import ServiceError

from .test_component_context_replicas import _component, _context_input

# A rejected value raises a Pydantic ``ValidationError`` or a typed ``ServiceError``
# (the other config validators raise either, and a ``ServiceError`` is not wrapped).
_REJECTED = (ValidationError, ServiceError)

_GOOD_SUFFIX = "tailnet.example.ts.net"

# The fields of ``DeploymentConfig`` before this feature (read at commit fb5ef25e).
_CONFIG_KEYS_BEFORE_598 = {
    "ingress_class",
    "db_size",
    "backup_ttl",
    "fqdn_suffix",
    "external_url_scheme",
    "external_url_port",
    "external_dns_endpoints_type",
    "scheduling",
    "ip_whitelist",
    "dedicated_ingress",
    "env_vars",
    "runtime_class",
    "standard_storage",
    "fast_storage",
    "components",
}

# data-model.md: "the proposed default" rule for the override suffix. Lowercase letters, digits,
# hyphens and dots; labels of at most 63 characters; at most 253 characters in total; no empty
# string, no leading or trailing dot.
_INVALID_SUFFIXES = {
    "empty": "",
    "leading-dot": ".example.com",
    "trailing-dot": "example.com.",
    "empty-label": "a..example.com",
    "uppercase": "Example.com",
    "underscore": "my_domain.example.com",
    "space": "my domain.example.com",
    "slash": "example.com/path",
    "label-over-63": f"{'a' * 64}.example.com",
    "total-over-253": ".".join(["a" * 60] * 5),
    # A value that reaches a Kubernetes host or annotation must not carry a line break or
    # other whitespace or control character. ``re.match`` with ``$`` lets a trailing
    # newline through; the rule must match the whole value.
    "trailing-newline": "example.com\n",
    "leading-newline": "\nexample.com",
    "trailing-space": "example.com ",
    "leading-space": " example.com",
    "tab": "example\t.com",
    "trailing-tab": "example.com\t",
    "carriage-return": "example.com\r",
    "newline-inside-a-label": "exa\nmple.com",
    "newline-between-labels": "example\n.com",
    "null-byte": "example.com\x00",
    "non-breaking-space": "example\u00a0.com",
}
# The class is written to ``spec.ingressClassName`` and to the annotation
# ``kubernetes.io/ingress.class`` of the Ingress, so it must be a valid Kubernetes object name
# (a DNS-1123 subdomain: lowercase letters, digits, ``-`` and ``.``, starting and ending with a
# letter or a digit, at most 253 characters). Class names that the repository uses today.
_VALID_INGRESS_CLASSES = [
    "traefik",
    "nginx",
    "tailscale",
    "prod-nginx",
    "cluster-traefik",
    "ts",
    "a",
    "k8s.io-ingress-nginx",
    "a" * 63,
    ".".join(["a" * 63, "b" * 63, "c" * 63, "d" * 61]),
]
_INVALID_INGRESS_CLASSES = {
    "trailing-newline": "traefik\n",
    "leading-newline": "\ntraefik",
    "newline-inside": "tra\nefik",
    "carriage-return": "traefik\r",
    "tab": "tra\tefik",
    "space": "my class",
    "trailing-space": "traefik ",
    "leading-space": " traefik",
    "null-byte": "traefik\x00",
    "non-breaking-space": "tra\u00a0efik",
    "uppercase": "Traefik",
    "underscore": "my_class",
    "slash": "a/b",
    "colon": "a:b",
    "quote": 'a"b',
    "leading-hyphen": "-traefik",
    "trailing-hyphen": "traefik-",
    "leading-dot": ".traefik",
    "trailing-dot": "traefik.",
    "doubled-dot": "a..b",
    "hyphen-next-to-dot": "a-.b",
    "total-over-253": ".".join(["a" * 63, "b" * 63, "c" * 63, "d" * 62]),
}
_VALID_SUFFIXES = [
    _GOOD_SUFFIX,
    "example.com",
    "a-b.c1.io",
    f"{'a' * 63}.example.com",
]


def _block_class() -> Any:  # noqa: ANN401
    # Resolved at run time: a missing planned symbol raises ``AttributeError`` in the test that needs it.
    return importlib.import_module(
        "styrmin_backend.context.models.config"
    ).ServiceConfigBlock


def _deployment_config(services: object) -> DeploymentConfig:
    return DeploymentConfig.model_validate({"services": services})


class TestServiceConfigBlockFields:
    def test_both_fields_are_optional(self) -> None:
        block_cls = _block_class()

        empty = block_cls()
        class_only = block_cls(ingress_class="tailscale")
        suffix_only = block_cls(fqdn_suffix=_GOOD_SUFFIX)

        assert (empty.ingress_class, empty.fqdn_suffix) == (None, None)
        assert (class_only.ingress_class, class_only.fqdn_suffix) == (
            "tailscale",
            None,
        )
        assert (suffix_only.ingress_class, suffix_only.fqdn_suffix) == (
            None,
            _GOOD_SUFFIX,
        )

    def test_empty_ingress_class_is_rejected(self) -> None:
        block_cls = _block_class()
        assert block_cls(ingress_class="tailscale").ingress_class == "tailscale"

        with pytest.raises(_REJECTED) as exc_info:
            block_cls(ingress_class="")

        assert "ingress_class" in str(exc_info.value)

    def test_empty_ingress_class_is_rejected_in_a_deployment_config(self) -> None:
        _block_class()
        config = _deployment_config({"task-manager": {"ingress_class": "tailscale"}})
        assert config.services is not None

        with pytest.raises(_REJECTED) as exc_info:
            _deployment_config({"task-manager": {"ingress_class": ""}})

        assert "ingress_class" in str(exc_info.value)

    @pytest.mark.parametrize("ingress_class", _VALID_INGRESS_CLASSES)
    def test_valid_ingress_class_is_accepted(self, ingress_class: str) -> None:
        block = _block_class()(ingress_class=ingress_class)

        assert block.ingress_class == ingress_class

    @pytest.mark.parametrize(
        "ingress_class",
        list(_INVALID_INGRESS_CLASSES.values()),
        ids=list(_INVALID_INGRESS_CLASSES),
    )
    def test_invalid_ingress_class_is_rejected(self, ingress_class: str) -> None:
        block_cls = _block_class()
        assert block_cls(ingress_class="traefik").ingress_class == "traefik"

        with pytest.raises(_REJECTED) as exc_info:
            block_cls(ingress_class=ingress_class)

        assert "ingress_class" in str(exc_info.value)

    def test_invalid_ingress_class_is_rejected_in_a_deployment_config(self) -> None:
        _block_class()
        config = _deployment_config({"task-manager": {"ingress_class": "traefik"}})
        assert config.services is not None

        with pytest.raises(_REJECTED) as exc_info:
            _deployment_config({"task-manager": {"ingress_class": "traefik\n"}})

        assert "ingress_class" in str(exc_info.value)

    @pytest.mark.parametrize("suffix", _VALID_SUFFIXES)
    def test_valid_suffix_is_accepted(self, suffix: str) -> None:
        block = _block_class()(fqdn_suffix=suffix)

        assert block.fqdn_suffix == suffix

    @pytest.mark.parametrize(
        "suffix", list(_INVALID_SUFFIXES.values()), ids=list(_INVALID_SUFFIXES)
    )
    def test_invalid_suffix_is_rejected(self, suffix: str) -> None:
        block_cls = _block_class()
        assert block_cls(fqdn_suffix=_GOOD_SUFFIX).fqdn_suffix == _GOOD_SUFFIX

        with pytest.raises(_REJECTED) as exc_info:
            block_cls(fqdn_suffix=suffix)

        assert "fqdn_suffix" in str(exc_info.value)

    def test_invalid_suffix_is_rejected_in_a_deployment_config(self) -> None:
        _block_class()
        config = _deployment_config({"task-manager": {"fqdn_suffix": _GOOD_SUFFIX}})
        assert config.services is not None

        with pytest.raises(_REJECTED) as exc_info:
            _deployment_config({"task-manager": {"fqdn_suffix": "Not A Name"}})

        assert "fqdn_suffix" in str(exc_info.value)

    @pytest.mark.parametrize(
        "extra_key", ["name", "tls_hosts", "ingressClass", "replicas"]
    )
    def test_other_keys_are_rejected(self, extra_key: str) -> None:
        block_cls = _block_class()
        assert block_cls(ingress_class="tailscale").ingress_class == "tailscale"

        with pytest.raises(ValidationError) as exc_info:
            block_cls.model_validate({"ingress_class": "tailscale", extra_key: "x"})

        assert extra_key in str(exc_info.value)
        assert "extra" in str(exc_info.value).lower()

    def test_other_keys_are_rejected_in_a_deployment_config(self) -> None:
        _block_class()
        assert _deployment_config({"task-manager": {"ingress_class": "a"}}).services

        with pytest.raises(ValidationError) as exc_info:
            _deployment_config(
                {"task-manager": {"ingress_class": "a", "tls_hosts": ["a.test"]}}
            )

        assert "tls_hosts" in str(exc_info.value)


class TestDeploymentConfigServices:
    def test_services_default_to_none(self) -> None:
        _block_class()

        assert DeploymentConfig().services is None
        assert DeploymentConfig(services=None).services is None

    def test_blocks_are_keyed_by_the_driver_service_name(self) -> None:
        block_cls = _block_class()

        config = _deployment_config(
            {
                "task-manager": {
                    "ingress_class": "tailscale",
                    "fqdn_suffix": _GOOD_SUFFIX,
                },
                "infrahub": {"ingress_class": "traefik"},
            }
        )

        assert config.services is not None
        assert set(config.services) == {"task-manager", "infrahub"}
        assert isinstance(config.services["task-manager"], block_cls)
        assert config.services["task-manager"].ingress_class == "tailscale"
        assert config.services["task-manager"].fqdn_suffix == _GOOD_SUFFIX
        assert config.services["infrahub"].fqdn_suffix is None

    @pytest.mark.parametrize(
        "empty_block",
        [{}, {"ingress_class": None, "fqdn_suffix": None}],
        ids=["no-keys", "both-none"],
    )
    def test_a_block_with_both_fields_none_is_dropped(
        self, empty_block: dict[str, Any]
    ) -> None:
        """data-model: "A block with both fields ``None`` is not stored"."""
        _block_class()

        config = _deployment_config(
            {"task-manager": empty_block, "infrahub": {"ingress_class": "traefik"}}
        )

        assert config.services is not None
        assert set(config.services) == {"infrahub"}
        assert set(config.model_dump(mode="json")["services"]) == {"infrahub"}

    def test_a_services_dict_of_only_empty_blocks_stores_no_override(self) -> None:
        _block_class()

        config = _deployment_config({"task-manager": {}})

        assert not config.services
        assert not config.model_dump(mode="json").get("services")

    @pytest.mark.parametrize("mode", ["python", "json"])
    def test_a_block_with_an_override_is_dumped(self, mode: str) -> None:
        _block_class()
        config = _deployment_config(
            {
                "task-manager": {
                    "ingress_class": "tailscale",
                    "fqdn_suffix": _GOOD_SUFFIX,
                }
            }
        )

        dumped = config.model_dump(mode=mode)

        assert dumped["services"]["task-manager"]["ingress_class"] == "tailscale"
        assert dumped["services"]["task-manager"]["fqdn_suffix"] == _GOOD_SUFFIX


class TestConfigWithoutServicesIsUnchanged:
    """FR-015: the stored config of an existing deployment does not change."""

    @pytest.mark.parametrize("mode", ["python", "json"])
    def test_config_without_services_dumps_the_keys_it_had_before(
        self, mode: str
    ) -> None:
        assert set(DeploymentConfig().model_dump(mode=mode)) == _CONFIG_KEYS_BEFORE_598

    @pytest.mark.parametrize("mode", ["python", "json"])
    def test_config_with_services_none_dumps_the_keys_it_had_before(
        self, mode: str
    ) -> None:
        dumped = DeploymentConfig.model_validate({"services": None}).model_dump(
            mode=mode
        )

        assert set(dumped) == _CONFIG_KEYS_BEFORE_598

    @pytest.mark.parametrize("mode", ["python", "json"])
    def test_config_with_services_dumps_the_key(self, mode: str) -> None:
        _block_class()
        config = _deployment_config({"task-manager": {"ingress_class": "tailscale"}})

        assert set(config.model_dump(mode=mode)) == _CONFIG_KEYS_BEFORE_598 | {
            "services"
        }

    def test_stored_config_of_an_existing_deployment_round_trips_unchanged(
        self,
    ) -> None:
        """A config written before #598 reads and dumps as the same dict (the no-op check of an update sees no change).

        Passes before the implementation too: it guards the behaviour the new field must not change.
        """
        stored: dict[str, Any] = {
            "fqdn_suffix": "test.styrmin.com",
            "ingress_class": "traefik",
            "ip_whitelist": ["10.0.0.0/8"],
            "env_vars": {"A": "1"},
            "components": {"server": {"env_vars": {"B": "2"}, "replicas": 2}},
        }

        reloaded = DeploymentConfig.model_validate(stored)

        assert reloaded.model_dump(mode="json", exclude_none=True) == stored
        assert "services" not in reloaded.model_dump(mode="json")

    def test_stored_config_with_services_round_trips_unchanged(self) -> None:
        _block_class()
        stored: dict[str, Any] = {
            "fqdn_suffix": "test.styrmin.com",
            "services": {
                "task-manager": {
                    "ingress_class": "tailscale",
                    "fqdn_suffix": _GOOD_SUFFIX,
                },
                "infrahub": {"ingress_class": "traefik"},
            },
        }

        reloaded = DeploymentConfig.model_validate(stored)

        assert reloaded.model_dump(mode="json", exclude_none=True) == stored

    @pytest.mark.parametrize("mode", ["python", "json"])
    def test_resolved_context_without_override_has_no_services_key(
        self, mode: str
    ) -> None:
        _block_class()
        with_override = resolve_global_context(
            context_input=_context_input(
                _component("server"),
                deployment_config={
                    "services": {"task-manager": {"ingress_class": "tailscale"}}
                },
            )
        )
        without_override = resolve_global_context(
            context_input=_context_input(_component("server"))
        )

        dumped_with = with_override.model_dump(mode=mode)
        dumped_without = without_override.model_dump(mode=mode)

        for scope in ("deployment", "instance"):
            assert "services" in dumped_with[scope]["config"]
            assert "services" not in dumped_without[scope]["config"]


@pytest.mark.parametrize("tls", [None, False, True])
def test_service_tls_opt_in_preserves_existing_config_shape(tls: bool | None) -> None:
    block = _block_class()(ingress_class="tailscale", tls=tls)
    dumped = block.model_dump()
    assert block.tls is tls
    if tls is None:
        assert "tls" not in dumped
    else:
        assert dumped["tls"] is tls
    assert not block.is_empty


def test_tls_only_service_override_is_kept() -> None:
    config = DeploymentConfig(services={"task-manager": _block_class()(tls=True)})
    assert config.model_dump()["services"]["task-manager"]["tls"] is True
