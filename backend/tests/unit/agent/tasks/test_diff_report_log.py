"""The diff report that the task worker logs holds no env var value (#573).

``_plan_remediation`` logs one "Flow-side diff report" line at INFO for each
create and update. The line held the whole report: every env var value, the
old and the new value on an update, the parameters and the values template.
Prefect stores the line in its log table too.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from loguru import logger
from tests.helpers.secret_context import TEMPLATE_SECRETS, secret_context
from tests.helpers.unit_of_work import yield_unit_of_work

from styrmin_backend.context.models.components import (
    ArbitrarySectionModel,
    ComponentContext,
    ComponentsContext,
    Identifier,
    LabelIdentifier,
    ResolvedComponentEnvVars,
)
from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.domain.models import Instance, InstanceStatus
from styrmin_backend.services.reconciliation.diffs.comparison import Comparator

MODULE = "styrmin_backend.agent.tasks.orchestration"

OLD_SECRET = "FAKE573-pw-1111"
NEW_SECRET = "FAKE573-pw-3333"
PLAIN = "FAKE573-plain-value"


def _instance(
    *, secret: str, deployment_id: UUID, driver_version_id: UUID, version: str
) -> Instance:
    return Instance(
        id=uuid4(),
        name="instance",
        application_version=version,
        status=InstanceStatus.PENDING,
        deployment_id=deployment_id,
        application_driver_version_id=driver_version_id,
        context=secret_context(
            env_secret=secret, plain_secret=PLAIN, deployment_id=deployment_id
        ),
    )


@pytest.fixture
def run_log() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    run_logger = logging.getLogger("test.flow_run")
    handler = logging.StreamHandler(stream)
    run_logger.addHandler(handler)
    run_logger.setLevel(logging.INFO)
    run_logger.propagate = False
    try:
        yield stream
    finally:
        run_logger.removeHandler(handler)


async def _plan(current: Instance | None, new: Instance) -> None:
    from styrmin_backend.agent.tasks.orchestration import _plan_remediation

    entities = {new.id: new} | ({current.id: current} if current else {})
    uow = AsyncMock()
    uow.deployments.find = AsyncMock(return_value=MagicMock())
    uow.application_instances.get = AsyncMock(
        side_effect=lambda *, id: MagicMock(id=id)
    )
    with (
        patch(f"{MODULE}.get_unit_of_work", yield_unit_of_work(uow)),
        patch(
            f"{MODULE}._build_instance_entity",
            side_effect=lambda model: entities[model.id] if model else None,
        ),
        patch(f"{MODULE}.Remediator") as remediator,
        patch(
            f"{MODULE}.get_run_logger",
            return_value=logging.getLogger("test.flow_run"),
        ),
    ):
        remediator.return_value.generate_remediation = AsyncMock(return_value=None)
        await _plan_remediation(
            deployment_id=new.deployment_id,
            new_instance_id=new.id,
            current_instance_id=current.id if current else None,
        )


@pytest.mark.asyncio
async def test_the_diff_report_of_a_create_names_the_instance_not_the_values(
    run_log: io.StringIO,
) -> None:
    new = _instance(
        secret=OLD_SECRET,
        deployment_id=uuid4(),
        driver_version_id=uuid4(),
        version="1.11.7",
    )

    await _plan(None, new)

    text = run_log.getvalue()
    assert "Flow-side diff report: create instance" in text
    assert str(new.id) in text
    assert str(new.deployment_id) in text
    for secret in (OLD_SECRET, PLAIN, "FAKE573-param-pw", *TEMPLATE_SECRETS):
        assert secret not in text


@pytest.mark.asyncio
async def test_the_diff_report_of_an_update_names_what_changed_not_the_values(
    run_log: io.StringIO,
) -> None:
    deployment_id, driver_version_id = uuid4(), uuid4()
    current = _instance(
        secret=OLD_SECRET,
        deployment_id=deployment_id,
        driver_version_id=driver_version_id,
        version="1.11.7",
    )
    new = _instance(
        secret=NEW_SECRET,
        deployment_id=deployment_id,
        driver_version_id=driver_version_id,
        version="1.11.8",
    )

    await _plan(current, new)

    text = run_log.getvalue()
    assert "Flow-side diff report: update to instance" in text
    assert "application version 1.11.7 -> 1.11.8" in text
    assert "deployment.config.env_vars.APP_ADMIN_PASSWORD" in text
    for secret in (OLD_SECRET, NEW_SECRET, PLAIN, *TEMPLATE_SECRETS):
        assert secret not in text


def test_printing_a_diff_report_shows_no_value() -> None:
    deployment_id, driver_version_id = uuid4(), uuid4()
    current = _instance(
        secret=OLD_SECRET,
        deployment_id=deployment_id,
        driver_version_id=driver_version_id,
        version="1.11.7",
    )
    new = _instance(
        secret=NEW_SECRET,
        deployment_id=deployment_id,
        driver_version_id=driver_version_id,
        version="1.11.7",
    )

    report = Comparator(current_instance=current, new_instance=new).compare()

    for text in (str(report), repr(report)):
        for secret in (OLD_SECRET, NEW_SECRET, PLAIN, *TEMPLATE_SECRETS):
            assert secret not in text


def test_the_warning_for_changes_without_an_entry_names_paths_not_values() -> None:
    # A change that DeepDiff reports outside ``values_changed`` (here a type
    # change, None -> dict) produces no diff entry, and Comparator logs a warning.
    deployment_id = uuid4()
    new = _instance(
        secret=NEW_SECRET,
        deployment_id=deployment_id,
        driver_version_id=uuid4(),
        version="1.11.7",
    )
    old_context = new.context.model_copy(deep=True)
    old_context.deployment.config.env_vars = None
    current = new.model_copy(update={"id": uuid4(), "context": old_context})
    stream = io.StringIO()
    handler_id = logger.add(stream, level="WARNING", format="{message}")
    try:
        report = Comparator(current_instance=current, new_instance=new).compare()
    finally:
        logger.remove(handler_id)

    text = stream.getvalue()
    assert report.diff is None
    assert "root['context']['deployment']['config']['env_vars']" in text
    for secret in (NEW_SECRET, PLAIN):
        assert secret not in text


def test_describe_names_a_deletion_and_no_change() -> None:
    from styrmin_backend.services.reconciliation.diffs.diffs import (
        DiffReport,
        InstanceDeletion,
    )

    current = _instance(
        secret=OLD_SECRET,
        deployment_id=uuid4(),
        driver_version_id=uuid4(),
        version="1.11.7",
    )

    assert DiffReport(diff=None, raw=None).describe() == "no change"
    assert DiffReport(diff=InstanceDeletion(instance=current), raw=None).describe() == (
        f"delete instance {current.id} of deployment {current.deployment_id}"
    )


def test_changed_paths_names_keys_not_values() -> None:
    from styrmin_backend.services.reconciliation.diffs.diffs import changed_paths

    current = {"env_vars": {"A": OLD_SECRET, "B": "same"}, "gone": 1, "list": [1]}
    new = {"env_vars": {"A": NEW_SECRET, "B": "same"}, "added": 2, "list": [2]}

    assert changed_paths(current, new) == ["added", "env_vars.A", "gone", "list"]


def _with_canary(context: GlobalContext, canary: str | None) -> GlobalContext:
    """``context`` with the env var ``E2E_LOG_CANARY`` set to ``canary``, or no env vars.

    The shape of a deployment that had no env vars at deployment scope and gets
    one: ``deployment.config.env_vars`` and ``instance.config.env_vars`` go from
    ``None`` to a dict, and the component's resolved ``env_vars`` block from
    ``None`` to a block.
    """
    env_vars = None if canary is None else {"E2E_LOG_CANARY": canary}
    context = context.model_copy(deep=True)
    context.deployment.config.env_vars = env_vars
    context.instance.config.env_vars = env_vars
    context.components = ComponentsContext(
        {
            "server": ComponentContext(
                name="server",
                enabled=True,
                config=ArbitrarySectionModel(
                    identifier=Identifier(
                        label=LabelIdentifier(root={"app": "server"})
                    ),
                ),
                env_vars=(
                    None
                    if env_vars is None
                    else ResolvedComponentEnvVars(
                        config=env_vars, provenance={"E2E_LOG_CANARY": "deployment"}
                    )
                ),
            )
        }
    )
    return context


@pytest.mark.asyncio
async def test_the_diff_report_names_an_env_var_set_where_the_scope_had_none(
    run_log: io.StringIO,
) -> None:
    # The E2E test ``test_env_var_values_stay_out_of_the_logs``, run alone, sets
    # the first deployment-scope env var: the report named only
    # ``deployment.config.env_vars``, because one side was ``None``.
    canary = "FAKE573-canary-9999"
    deployment_id, driver_version_id = uuid4(), uuid4()
    current = _instance(
        secret=OLD_SECRET,
        deployment_id=deployment_id,
        driver_version_id=driver_version_id,
        version="1.11.7",
    )
    new = _instance(
        secret=OLD_SECRET,
        deployment_id=deployment_id,
        driver_version_id=driver_version_id,
        version="1.11.7",
    )
    current.context = _with_canary(current.context, None)
    new.context = _with_canary(new.context, canary)

    await _plan(current, new)

    text = run_log.getvalue()
    assert "deployment.config.env_vars.E2E_LOG_CANARY" in text
    assert "instance.config.env_vars.E2E_LOG_CANARY" in text
    assert "components.server.env_vars.config.E2E_LOG_CANARY" in text
    assert canary not in text

    # And back: the env var is removed, the scope has none again.
    run_log.seek(0)
    run_log.truncate()
    await _plan(new, current)

    assert "deployment.config.env_vars.E2E_LOG_CANARY" in run_log.getvalue()


def test_describe_counts_the_paths_past_the_limit() -> None:
    from styrmin_backend.services.reconciliation.diffs.diffs import (
        MAX_DESCRIBED_PATHS,
        ContextChange,
    )

    new = {f"K{index:03d}": "x" for index in range(MAX_DESCRIBED_PATHS + 10)}

    text = ContextChange(current_value={}, new_value=new).describe()

    assert text.endswith(" and 10 more")
    assert f"K{MAX_DESCRIBED_PATHS - 1:03d}" in text
    assert f"K{MAX_DESCRIBED_PATHS:03d}" not in text
