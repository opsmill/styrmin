"""The device schema file and the Infrahub setup helper, with a fake Infrahub client."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
import yaml

from tests.e2e.demos import infrahub_setup
from tests.e2e.demos.infrahub_setup import SCHEMA_PATH, InfrahubSetupError, load_devices


def test_the_schema_defines_the_network_device_kind_of_research_r008() -> None:
    schema = yaml.safe_load(SCHEMA_PATH.read_text())

    (node,) = schema["nodes"]
    assert f"{node['namespace']}{node['name']}" == infrahub_setup.DEVICE_KIND
    assert node["label"] == "Network device"
    assert node["icon"] == "mdi:router-network"
    assert node["display_label"] == "{{ name__value }}"
    assert node["human_friendly_id"] == ["name__value"]
    assert node["attributes"] == [{"name": "name", "kind": "Text", "unique": True}]


class FakeInfrahub:
    def __init__(self, errors: dict) -> None:
        self.errors = errors
        self.loaded: list[tuple] = []
        self.saved: list[str] = []
        self.schema = SimpleNamespace(load=self._load)

    async def _load(self, *, schemas, wait_until_converged):
        self.loaded.append((schemas, wait_until_converged))
        return SimpleNamespace(errors=self.errors)

    async def create(self, *, kind, name):
        assert kind == "InfraDevice"
        saved = self.saved

        async def save() -> None:
            saved.append(name)

        return SimpleNamespace(save=save)


async def test_load_devices_loads_the_schema_then_creates_each_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeInfrahub(errors={})
    monkeypatch.setattr(infrahub_setup, "client", lambda _url: fake)

    await load_devices("http://infrahub-lab.local.styrmin.io:8080", ["sw1", "sw2"])

    ((schemas, converged),) = fake.loaded
    assert schemas == [yaml.safe_load(SCHEMA_PATH.read_text())]
    assert converged is True
    assert fake.saved == ["sw1", "sw2"]


async def test_load_devices_raises_and_creates_nothing_when_infrahub_refuses_the_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeInfrahub(errors={"errors": [{"message": "namespace is restricted"}]})
    monkeypatch.setattr(infrahub_setup, "client", lambda _url: fake)

    with pytest.raises(InfrahubSetupError, match="namespace is restricted"):
        await load_devices("http://infrahub-lab.local.styrmin.io:8080", ["sw1"])
    assert fake.saved == []
