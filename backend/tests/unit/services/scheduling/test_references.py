"""Unit tests for finding, binding and remapping the deployment references in stored configs."""

from __future__ import annotations

import copy
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from styrmin_backend.context.models.config import EnvironmentConfig
from styrmin_backend.db.models import Cluster
from styrmin_backend.domain.models import Deployment, DeploymentState
from styrmin_backend.services.exceptions import UnresolvableAffinityReferenceError
from styrmin_backend.services.scheduling.references import (
    bind_deployment_references,
    iter_reference_sites,
    referenced_deployment_ids,
    remap_deployment_references,
)
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork

pytestmark = pytest.mark.anyio

_TOPOLOGY_KEY = "kubernetes.io/hostname"


def _make_deployment(
    *, name: str, environment_id: UUID, deleted: bool = False
) -> Deployment:
    return Deployment(
        id=uuid4(),
        name=name,
        application_version="1.0.0",
        config=None,
        application_driver_version_id=uuid4(),
        environment_id=environment_id,
        status=DeploymentState.DELETED if deleted else DeploymentState.RUNNING,
        deleted_at=datetime.now(UTC) if deleted else None,
        created_by_user_id=uuid4(),
    )


def _term(ref: dict[str, Any]) -> dict[str, Any]:
    return {"topology_key": _TOPOLOGY_KEY, "deployment_ref": ref}


def _config(
    *,
    required: list[dict[str, Any]] | None = None,
    preferred: list[dict[str, Any]] | None = None,
    kind: str = "pod_affinity",
) -> dict[str, Any]:
    block: dict[str, Any] = {}
    if required is not None:
        block["required"] = [_term(ref) for ref in required]
    if preferred is not None:
        block["preferred"] = [{"weight": 50, "term": _term(ref)} for ref in preferred]
    return {"scheduling": {kind: block}}


def _required_ref(
    config: dict[str, Any], idx: int = 0, kind: str = "pod_affinity"
) -> dict[str, Any]:
    return config["scheduling"][kind]["required"][idx]["deployment_ref"]


def _preferred_ref(
    config: dict[str, Any], idx: int = 0, kind: str = "pod_affinity"
) -> dict[str, Any]:
    return config["scheduling"][kind]["preferred"][idx]["term"]["deployment_ref"]


class TestIterReferenceSites:
    def test_paths_cover_required_and_preferred_of_both_pod_kinds(self) -> None:
        config = {
            "scheduling": {
                "pod_affinity": {
                    "required": [_term({"deployment_name": "a"})],
                    "preferred": [
                        {"weight": 10, "term": _term({"deployment_name": "b"})}
                    ],
                },
                "pod_anti_affinity": {
                    "required": [
                        {"topology_key": _TOPOLOGY_KEY},
                        _term({"deployment_name": "c"}),
                    ],
                    "preferred": [
                        {"weight": 10, "term": _term({"deployment_name": "d"})}
                    ],
                },
            }
        }

        sites = list(iter_reference_sites(config, "environment.config"))

        assert [site.path for site in sites] == [
            "environment.config.scheduling.pod_affinity.required[0]",
            "environment.config.scheduling.pod_affinity.preferred[0].term",
            "environment.config.scheduling.pod_anti_affinity.required[1]",
            "environment.config.scheduling.pod_anti_affinity.preferred[0].term",
        ]
        assert [site.deployment_ref["deployment_name"] for site in sites] == [
            "a",
            "b",
            "c",
            "d",
        ]

    def test_configs_without_scheduling_yield_nothing(self) -> None:
        assert list(iter_reference_sites(None, "deployment.config")) == []
        assert list(iter_reference_sites({}, "deployment.config")) == []
        assert (
            list(iter_reference_sites({"scheduling": None}, "deployment.config")) == []
        )
        assert (
            list(
                iter_reference_sites(
                    {"scheduling": {"pod_affinity": None}}, "deployment.config"
                )
            )
            == []
        )


class TestReferencedDeploymentIds:
    def test_maps_each_id_to_every_path_that_names_it(self) -> None:
        a, b = uuid4(), uuid4()
        config = _config(
            required=[{"deployment_id": str(a)}, {"deployment_id": str(b)}],
            preferred=[
                {"deployment_id": str(a).upper()},
                {"deployment_name": "by-name"},
            ],
        )

        assert referenced_deployment_ids(config, "deployment[api].config") == {
            a: [
                "deployment[api].config.scheduling.pod_affinity.required[0]",
                "deployment[api].config.scheduling.pod_affinity.preferred[0].term",
            ],
            b: ["deployment[api].config.scheduling.pod_affinity.required[1]"],
        }


class TestBindByName:
    async def test_name_becomes_id_at_required_and_preferred(self, uow) -> None:  # type: ignore[no-untyped-def]
        env_id = uuid4()
        a = _make_deployment(name="a", environment_id=env_id)
        b = _make_deployment(name="b", environment_id=env_id)
        await uow.deployments.save(a)
        await uow.deployments.save(b)
        config = _config(
            required=[{"deployment_name": "a"}], preferred=[{"deployment_name": "b"}]
        )

        bound = await bind_deployment_references(
            uow, env_id, config, path_prefix="deployment.config"
        )

        assert bound is not None
        assert _required_ref(bound) == {"deployment_id": str(a.id)}
        assert _preferred_ref(bound) == {"deployment_id": str(b.id)}

    async def test_components_are_kept_only_when_given(self, uow) -> None:  # type: ignore[no-untyped-def]
        env_id = uuid4()
        a = _make_deployment(name="a", environment_id=env_id)
        await uow.deployments.save(a)
        config = _config(
            required=[
                {"deployment_name": "a", "components": ["primary", "replica"]},
                {"deployment_name": "a", "components": None},
            ]
        )

        bound = await bind_deployment_references(
            uow, env_id, config, path_prefix="deployment.config"
        )

        assert bound is not None
        assert _required_ref(bound, 0) == {
            "deployment_id": str(a.id),
            "components": ["primary", "replica"],
        }
        assert _required_ref(bound, 1) == {"deployment_id": str(a.id)}

    async def test_missing_name_is_refused_with_full_path(self, uow) -> None:  # type: ignore[no-untyped-def]
        config = _config(
            preferred=[{"deployment_name": "nope"}], kind="pod_anti_affinity"
        )

        with pytest.raises(UnresolvableAffinityReferenceError) as exc:
            await bind_deployment_references(
                uow, uuid4(), config, path_prefix="environment.config"
            )

        assert exc.value.error_metadata == {
            "deployment_name": "nope",
            "path": "environment.config.scheduling.pod_anti_affinity.preferred[0].term",
        }

    async def test_name_of_another_environment_is_refused(self, uow) -> None:  # type: ignore[no-untyped-def]
        other = _make_deployment(name="a", environment_id=uuid4())
        await uow.deployments.save(other)

        with pytest.raises(UnresolvableAffinityReferenceError) as exc:
            await bind_deployment_references(
                uow,
                uuid4(),
                _config(required=[{"deployment_name": "a"}]),
                path_prefix="deployment.config",
            )

        assert exc.value.error_metadata["deployment_name"] == "a"

    async def test_name_of_tombstoned_deployment_is_refused(self, uow) -> None:  # type: ignore[no-untyped-def]
        env_id = uuid4()
        await uow.deployments.save(
            _make_deployment(name="a", environment_id=env_id, deleted=True)
        )

        with pytest.raises(UnresolvableAffinityReferenceError) as exc:
            await bind_deployment_references(
                uow,
                env_id,
                _config(required=[{"deployment_name": "a"}]),
                path_prefix="deployment.config",
            )

        assert exc.value.error_metadata == {
            "deployment_name": "a",
            "path": "deployment.config.scheduling.pod_affinity.required[0]",
        }

    async def test_first_failing_term_gives_the_path(self, uow) -> None:  # type: ignore[no-untyped-def]
        env_id = uuid4()
        await uow.deployments.save(_make_deployment(name="a", environment_id=env_id))
        config = _config(
            required=[{"deployment_name": "a"}, {"deployment_name": "first-missing"}],
            preferred=[{"deployment_name": "second-missing"}],
        )

        with pytest.raises(UnresolvableAffinityReferenceError) as exc:
            await bind_deployment_references(
                uow, env_id, config, path_prefix="deployment.config"
            )

        assert exc.value.error_metadata["deployment_name"] == "first-missing"
        assert (
            exc.value.error_metadata["path"]
            == "deployment.config.scheduling.pod_affinity.required[1]"
        )


class TestBindById:
    async def test_uppercase_id_is_stored_in_canonical_form(self, uow) -> None:  # type: ignore[no-untyped-def]
        env_id = uuid4()
        a = _make_deployment(name="a", environment_id=env_id)
        await uow.deployments.save(a)
        config = _config(
            required=[{"deployment_id": str(a.id).upper(), "components": ["primary"]}]
        )

        bound = await bind_deployment_references(
            uow, env_id, config, path_prefix="deployment.config"
        )

        assert bound is not None
        assert _required_ref(bound) == {
            "deployment_id": str(a.id),
            "components": ["primary"],
        }

    async def test_missing_id_is_refused(self, uow) -> None:  # type: ignore[no-untyped-def]
        missing = uuid4()

        with pytest.raises(UnresolvableAffinityReferenceError) as exc:
            await bind_deployment_references(
                uow,
                uuid4(),
                _config(required=[{"deployment_id": str(missing)}]),
                path_prefix="deployment.config",
            )

        assert exc.value.error_metadata == {
            "deployment_id": str(missing),
            "path": "deployment.config.scheduling.pod_affinity.required[0]",
        }

    async def test_id_of_another_environment_is_refused(self, uow) -> None:  # type: ignore[no-untyped-def]
        other = _make_deployment(name="a", environment_id=uuid4())
        await uow.deployments.save(other)

        with pytest.raises(UnresolvableAffinityReferenceError) as exc:
            await bind_deployment_references(
                uow,
                uuid4(),
                _config(required=[{"deployment_id": str(other.id)}]),
                path_prefix="deployment.config",
            )

        assert exc.value.error_metadata["deployment_id"] == str(other.id)
        assert "deleted" not in exc.value.error_metadata

    async def test_tombstoned_id_is_refused_with_last_name_and_deleted(
        self, uow
    ) -> None:  # type: ignore[no-untyped-def]
        env_id = uuid4()
        gone = _make_deployment(name="postgres", environment_id=env_id, deleted=True)
        await uow.deployments.save(gone)
        config = _config(preferred=[{"deployment_id": str(gone.id)}])

        with pytest.raises(UnresolvableAffinityReferenceError) as exc:
            await bind_deployment_references(
                uow, env_id, config, path_prefix="deployment.config"
            )

        path = "deployment.config.scheduling.pod_affinity.preferred[0].term"
        assert exc.value.error_metadata == {
            "deployment_id": str(gone.id),
            "deployment_name": "postgres",
            "path": path,
            "deleted": True,
        }
        assert (
            str(exc.value)
            == f"Affinity term at {path} names deployment 'postgres' ({gone.id}), which was deleted"
        )


class TestBindUpcomingDeployments:
    async def test_upcoming_name_gives_its_id_without_a_row(self, uow) -> None:  # type: ignore[no-untyped-def]
        new_id = uuid4()

        bound = await bind_deployment_references(
            uow,
            uuid4(),
            _config(required=[{"deployment_name": "new"}]),
            path_prefix="deployment.config",
            upcoming_deployments={new_id: "new"},
        )

        assert bound is not None
        assert _required_ref(bound) == {"deployment_id": str(new_id)}

    async def test_upcoming_id_is_accepted_without_a_row(self, uow) -> None:  # type: ignore[no-untyped-def]
        new_id = uuid4()

        bound = await bind_deployment_references(
            uow,
            uuid4(),
            _config(required=[{"deployment_id": str(new_id).upper()}]),
            path_prefix="deployment.config",
            upcoming_deployments={new_id: "new"},
        )

        assert bound is not None
        assert _required_ref(bound) == {"deployment_id": str(new_id)}

    async def test_upcoming_name_wins_over_a_row_with_that_name(self, uow) -> None:  # type: ignore[no-untyped-def]
        env_id = uuid4()
        await uow.deployments.save(_make_deployment(name="b", environment_id=env_id))
        upcoming_id = uuid4()

        bound = await bind_deployment_references(
            uow,
            env_id,
            _config(required=[{"deployment_name": "b"}]),
            path_prefix="deployment.config",
            upcoming_deployments={upcoming_id: "b"},
        )

        assert bound is not None
        assert _required_ref(bound) == {"deployment_id": str(upcoming_id)}

    async def test_old_name_of_a_renamed_deployment_is_refused(self, uow) -> None:  # type: ignore[no-untyped-def]
        env_id = uuid4()
        b = _make_deployment(name="b", environment_id=env_id)
        await uow.deployments.save(b)
        upcoming = {b.id: "b2"}

        bound = await bind_deployment_references(
            uow,
            env_id,
            _config(required=[{"deployment_name": "b2"}]),
            path_prefix="deployment.config",
            upcoming_deployments=upcoming,
        )
        assert bound is not None
        assert _required_ref(bound) == {"deployment_id": str(b.id)}

        with pytest.raises(UnresolvableAffinityReferenceError) as exc:
            await bind_deployment_references(
                uow,
                env_id,
                _config(required=[{"deployment_name": "b"}]),
                path_prefix="deployment.config",
                upcoming_deployments=upcoming,
            )
        assert exc.value.error_metadata["deployment_name"] == "b"

    async def test_no_environment_matches_upcoming_deployments_only(self, uow) -> None:  # type: ignore[no-untyped-def]
        env_id = uuid4()
        existing = _make_deployment(name="existing", environment_id=env_id)
        await uow.deployments.save(existing)
        counterpart = uuid4()
        upcoming = {counterpart: "api"}

        bound = await bind_deployment_references(
            uow,
            None,
            _config(
                required=[{"deployment_name": "api"}],
                preferred=[{"deployment_id": str(counterpart)}],
            ),
            path_prefix="environment.config",
            upcoming_deployments=upcoming,
        )
        assert bound is not None
        assert _required_ref(bound) == {"deployment_id": str(counterpart)}
        assert _preferred_ref(bound) == {"deployment_id": str(counterpart)}

        for ref in (
            {"deployment_name": "existing"},
            {"deployment_id": str(existing.id)},
        ):
            with pytest.raises(UnresolvableAffinityReferenceError) as exc:
                await bind_deployment_references(
                    uow,
                    None,
                    _config(required=[ref]),
                    path_prefix="environment.config",
                    upcoming_deployments=upcoming,
                )
            assert (
                exc.value.error_metadata["path"]
                == "environment.config.scheduling.pod_affinity.required[0]"
            )


class TestBindLeavesTheRestAlone:
    async def test_node_affinity_and_other_keys_are_untouched(self, uow) -> None:  # type: ignore[no-untyped-def]
        env_id = uuid4()
        a = _make_deployment(name="a", environment_id=env_id)
        await uow.deployments.save(a)
        node_affinity = {
            "required": [
                {
                    "topology_key": "",
                    "label_selector": {"match_labels": {"disk": "ssd"}},
                    "deployment_ref": {"deployment_name": "not-a-deployment"},
                }
            ]
        }
        config = {
            "env_vars": {"LOG_LEVEL": "debug"},
            "scheduling": {
                "runtime_class": "kata",
                "node_affinity": copy.deepcopy(node_affinity),
                "pod_affinity": {
                    "required": [
                        {**_term({"deployment_name": "a"}), "namespaces": ["ns"]}
                    ],
                    "replace": True,
                },
            },
        }

        bound = await bind_deployment_references(
            uow, env_id, config, path_prefix="deployment.config"
        )

        assert bound == {
            "env_vars": {"LOG_LEVEL": "debug"},
            "scheduling": {
                "runtime_class": "kata",
                "node_affinity": node_affinity,
                "pod_affinity": {
                    "required": [
                        {
                            "topology_key": _TOPOLOGY_KEY,
                            "deployment_ref": {"deployment_id": str(a.id)},
                            "namespaces": ["ns"],
                        }
                    ],
                    "replace": True,
                },
            },
        }

    async def test_input_is_not_mutated(self, uow) -> None:  # type: ignore[no-untyped-def]
        env_id = uuid4()
        await uow.deployments.save(_make_deployment(name="a", environment_id=env_id))
        config = _config(required=[{"deployment_name": "a", "components": ["x"]}])
        before = copy.deepcopy(config)

        bound = await bind_deployment_references(
            uow, env_id, config, path_prefix="deployment.config"
        )

        assert config == before
        assert bound is not config

    async def test_config_without_references_is_returned_as_is(self, uow) -> None:  # type: ignore[no-untyped-def]
        config = {
            "scheduling": {"runtime_class": "kata"},
            "ip_whitelist": ["10.0.0.0/8"],
        }

        assert (
            await bind_deployment_references(
                uow, uuid4(), None, path_prefix="deployment.config"
            )
            is None
        )
        assert (
            await bind_deployment_references(
                uow, uuid4(), config, path_prefix="deployment.config"
            )
            is config
        )

    async def test_bound_config_survives_the_environment_config_round_trip(
        self, uow
    ) -> None:  # type: ignore[no-untyped-def]
        env_id = uuid4()
        a = _make_deployment(name="a", environment_id=env_id)
        b = _make_deployment(name="b", environment_id=env_id)
        await uow.deployments.save(a)
        await uow.deployments.save(b)
        written = EnvironmentConfig.model_validate(
            {
                "scheduling": {
                    "pod_anti_affinity": {
                        "required": [
                            _term({"deployment_name": "a", "components": ["primary"]})
                        ],
                        "preferred": [
                            {
                                "weight": 100,
                                "term": _term({"deployment_id": str(b.id).upper()}),
                            }
                        ],
                    }
                }
            }
        ).model_dump(exclude_none=True, mode="json")

        bound = await bind_deployment_references(
            uow, env_id, written, path_prefix="environment.config"
        )

        assert bound is not None
        round_trip = EnvironmentConfig.model_validate(bound).model_dump(
            exclude_none=True, mode="json"
        )
        assert round_trip == bound
        assert _required_ref(bound, kind="pod_anti_affinity") == {
            "deployment_id": str(a.id),
            "components": ["primary"],
        }
        assert _preferred_ref(bound, kind="pod_anti_affinity") == {
            "deployment_id": str(b.id)
        }


class TestRemapDeploymentReferences:
    def test_mutual_references_point_at_counterparts(self) -> None:
        a, b = uuid4(), uuid4()
        a2, b2 = uuid4(), uuid4()
        mapping = {a: a2, b: b2}
        a_config = _config(required=[{"deployment_id": str(b), "components": ["db"]}])
        b_config = _config(
            preferred=[{"deployment_id": str(a)}], kind="pod_anti_affinity"
        )
        a_before, b_before = copy.deepcopy(a_config), copy.deepcopy(b_config)

        a_remapped, a_unmapped = remap_deployment_references(a_config, mapping)
        b_remapped, b_unmapped = remap_deployment_references(b_config, mapping)

        assert a_remapped is not None
        assert b_remapped is not None
        assert _required_ref(a_remapped) == {
            "deployment_id": str(b2),
            "components": ["db"],
        }
        assert _preferred_ref(b_remapped, kind="pod_anti_affinity") == {
            "deployment_id": str(a2)
        }
        assert a_unmapped == {}
        assert b_unmapped == {}
        assert a_config == a_before
        assert b_config == b_before

    def test_unmapped_id_is_reported_with_its_path(self) -> None:
        a, a2, outside = uuid4(), uuid4(), uuid4()
        config = _config(
            required=[{"deployment_id": str(a)}],
            preferred=[{"deployment_id": str(outside)}],
        )

        remapped, unmapped = remap_deployment_references(
            config, {a: a2}, path_prefix="environment.config"
        )

        assert remapped is not None
        assert _required_ref(remapped) == {"deployment_id": str(a2)}
        assert _preferred_ref(remapped) == {"deployment_id": str(outside)}
        assert unmapped == {
            outside: ["environment.config.scheduling.pod_affinity.preferred[0].term"]
        }

    def test_none_config(self) -> None:
        assert remap_deployment_references(None, {uuid4(): uuid4()}) == (None, {})


class TestBindInsideTheCallersUnitOfWork:
    async def test_refusal_in_a_savepoint_keeps_the_callers_earlier_work(self) -> None:
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        config = _config(required=[{"deployment_name": "nope"}])
        try:
            async with AsyncSession(engine, expire_on_commit=False) as session:
                uow = SqlModelUnitOfWork(session)
                async with uow:
                    session.add(Cluster(name="before", config={}))
                    await session.flush()
                    with pytest.raises(UnresolvableAffinityReferenceError):
                        async with session.begin_nested():
                            async with uow:  # the service's own block
                                await bind_deployment_references(
                                    uow,
                                    uuid4(),
                                    config,
                                    path_prefix="deployment.config",
                                )
                    await uow.commit()
                names = set((await session.exec(select(Cluster.name))).all())
        finally:
            await engine.dispose()

        assert names == {"before"}
