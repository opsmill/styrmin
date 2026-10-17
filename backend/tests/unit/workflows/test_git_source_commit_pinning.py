"""User-action workflows run the commit their driver version was loaded from.

Regression coverage for issue #375: the Prefect deployments built for a
git-sourced driver's actions used to clone the *branch*, so a push to it
silently changed the code every existing deployment's actions ran. The
deployment's pull step must pin the commit recorded on the driver version
(``source_commit_sha``, ADR-053).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from prefect_github import GitHubCredentials

from styrmin_backend.services.driver.models.resources.actions import (
    ActionDefinition,
    HookKind,
)
from styrmin_backend.services.driver.models.structure.source import GitSource
from styrmin_backend.services.user import ActionsWorkflowBuilder
from styrmin_backend.workflows.constants import WorkflowType
from styrmin_backend.workflows.models import GitSourceWorkflowDefinition

REPOSITORY = "https://github.com/opsmill/lab-driver-a.git"
BRANCH = "master"
REV2 = "555d1558a741f3b4c9d0e1f2a3b4c5d6e7f80912"
GIT_CLONE_STEP = "prefect.deployments.steps.git_clone"
SET_DIRECTORY_STEP = "prefect.deployments.steps.set_working_directory"


@pytest.fixture(autouse=True)
def _saved_github_credentials(mocker):
    """``to_deployment`` loads the namespace's credentials block by name.

    Return an in-memory block that looks saved, so ``to_pull_step`` can
    render its ``{{ prefect.blocks... }}`` placeholder without a Prefect
    server.
    """
    block = GitHubCredentials(token="placeholder")
    block._block_document_name = "user-github-token"
    mocker.patch.object(GitHubCredentials, "load", AsyncMock(return_value=block))
    return block


def _definition(commit_sha: str | None, **overrides) -> GitSourceWorkflowDefinition:
    values = dict(
        name="User Action: post_setup",
        type=WorkflowType.USER,
        module="actions",
        function="post_setup",
        repository=REPOSITORY,
        branch=BRANCH,
        token="placeholder",
        namespace="user",
        commit_sha=commit_sha,
    )
    values.update(overrides)
    return GitSourceWorkflowDefinition(**values)


def _action() -> ActionDefinition:
    return ActionDefinition(
        name="post_setup",
        location="actions.py::post_setup",
        description="Log a marker after setup",
        hook=HookKind.SETUP,
        mode="post",
    )


# ---------------------------------------------------------------------------
# ActionsWorkflowBuilder → GitSourceWorkflowDefinition
# ---------------------------------------------------------------------------


def test_builder_pins_the_driver_version_commit() -> None:
    """The commit recorded on the driver version reaches every action workflow."""
    source = GitSource(repository=REPOSITORY, branch=BRANCH, token="placeholder")
    builder = ActionsWorkflowBuilder(source=source, commit_sha=REV2)

    workflow = builder.build_user_action_workflow_definition(action=_action())

    assert workflow.commit_sha == REV2
    assert workflow.branch == BRANCH
    assert workflow.repository == REPOSITORY


def test_builder_without_commit_keeps_tracking_the_branch() -> None:
    """No recorded commit (legacy rows) → unchanged branch-tip behaviour."""
    source = GitSource(repository=REPOSITORY, branch=BRANCH, token="placeholder")
    workflow = ActionsWorkflowBuilder(
        source=source
    ).build_user_action_workflow_definition(action=_action())

    assert workflow.commit_sha is None


# ---------------------------------------------------------------------------
# Prefect deployment pull steps
# ---------------------------------------------------------------------------


async def test_pull_step_checks_out_the_pinned_commit_not_the_branch() -> None:
    """The ``git_clone`` step carries ``commit_sha`` and no branch.

    Prefect refuses both at once; with only the commit, the worker fetches
    and checks out that exact commit regardless of where the branch tip
    has moved since the driver was loaded.
    """
    data = await _definition(commit_sha=REV2).to_deployment()

    (clone_step,) = data["pull_steps"]
    git_clone = clone_step[GIT_CLONE_STEP]
    assert git_clone["repository"] == REPOSITORY
    assert git_clone["commit_sha"] == REV2
    assert git_clone["branch"] is None
    # Prefect's default directory is derived from the branch, which is now
    # unset: name the checkout explicitly and per commit so a reused
    # working directory can never hand a different commit to this run.
    assert git_clone["clone_directory_name"] == "lab-driver-a-555d155"
    assert git_clone["credentials"] == (
        "{{ prefect.blocks.github-credentials.user-github-token }}"
    )


async def test_pull_step_without_commit_tracks_the_branch() -> None:
    """Legacy definitions without a commit keep Prefect's branch clone."""
    data = await _definition(commit_sha=None).to_deployment()

    (clone_step,) = data["pull_steps"]
    git_clone = clone_step[GIT_CLONE_STEP]
    assert git_clone["branch"] == BRANCH
    assert "commit_sha" not in git_clone
    assert "clone_directory_name" not in git_clone


@pytest.mark.parametrize(
    ("commit_sha", "expected_directory"),
    [
        (REV2, "lab-driver-a-555d155/backend"),
        (None, "lab-driver-a-master/backend"),
    ],
)
async def test_set_directory_step_follows_the_clone_directory(
    commit_sha: str | None, expected_directory: str
) -> None:
    """``set_directory`` must point inside whatever directory was cloned."""
    data = await _definition(
        commit_sha=commit_sha, set_directory="backend/"
    ).to_deployment()

    clone_step, set_directory_step = data["pull_steps"]
    clone_directory = clone_step[GIT_CLONE_STEP].get("clone_directory_name")
    assert set_directory_step[SET_DIRECTORY_STEP]["directory"] == expected_directory
    if clone_directory is not None:
        assert clone_directory in expected_directory


# ---------------------------------------------------------------------------
# Driver directory (spec 028): actions run from the driver directory
# ---------------------------------------------------------------------------


async def test_builder_with_driver_directory_adds_set_working_directory() -> None:
    """``git_clone`` then ``set_working_directory`` into the driver directory."""
    source = GitSource(
        repository=REPOSITORY,
        branch=BRANCH,
        token="placeholder",
        driver_directory="drivers/infrahub",
    )
    workflow = ActionsWorkflowBuilder(
        source=source, commit_sha=REV2
    ).build_user_action_workflow_definition(action=_action())

    assert workflow.set_directory == "drivers/infrahub"
    data = await workflow.to_deployment()
    assert [next(iter(step)) for step in data["pull_steps"]] == [
        GIT_CLONE_STEP,
        SET_DIRECTORY_STEP,
    ]
    clone_step, set_directory_step = data["pull_steps"]
    assert clone_step[GIT_CLONE_STEP]["clone_directory_name"] == "lab-driver-a-555d155"
    assert set_directory_step[SET_DIRECTORY_STEP] == {
        "directory": "lab-driver-a-555d155/drivers/infrahub"
    }


async def test_builder_without_driver_directory_keeps_one_pull_step() -> None:
    """A load from the repository root keeps only the ``git_clone`` step."""
    source = GitSource(repository=REPOSITORY, branch=BRANCH, token="placeholder")
    workflow = ActionsWorkflowBuilder(
        source=source, commit_sha=REV2
    ).build_user_action_workflow_definition(action=_action())

    assert workflow.set_directory is None
    data = await workflow.to_deployment()
    (clone_step,) = data["pull_steps"]
    assert GIT_CLONE_STEP in clone_step


def test_clone_directory_name_is_filesystem_safe_for_slashed_branches() -> None:
    """Mirror Prefect's ``<repo>-<branch>`` default, including ``/`` → ``-``."""
    definition = _definition(commit_sha=None, branch="feature/pin")
    assert definition.clone_directory_name == "lab-driver-a-feature-pin"
