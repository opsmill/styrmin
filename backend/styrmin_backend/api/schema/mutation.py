"""Provides the schema for the GraphQL API.

This is where the different routes and their types are defined.
"""

from __future__ import annotations

from uuid import UUID

import strawberry
from loguru import logger
from strawberry.permission import PermissionExtension

from styrmin_backend.api.auth.permissions import RequiresRole
from styrmin_backend.api.definitions.backup.backup import Backup as BackupType
from styrmin_backend.api.definitions.backup.environment_backup import (
    EnvironmentBackup as EnvironmentBackupType,
)
from styrmin_backend.api.definitions.backup.environment_restore import (
    EnvironmentRestore as EnvironmentRestoreType,
)
from styrmin_backend.api.definitions.backup.restore import Restore as RestoreType
from styrmin_backend.api.definitions.backup.schedule import (
    BackupSchedule as BackupScheduleType,
)
from styrmin_backend.api.definitions.application_driver.model import (
    ApplicationDriverVersion,
)
from styrmin_backend.api.definitions.backup_storage_location.model import (
    BackupStorageLocation as BackupStorageLocationType,
)
from styrmin_backend.api.definitions.callback.model import CallbackResponse
from styrmin_backend.api.definitions.pod_status.model import (
    DeploymentPodStatusReport,
    ReportPodStatusesResponse,
)
from styrmin_backend.api.definitions.deployment_status.model import (
    DeploymentStatusReportInput,
    ReportDeploymentStatusesResponse,
)
from styrmin_backend.api.definitions.cluster.model import Cluster
from styrmin_backend.api.definitions.deployment.inputs import (
    DeploymentConfigInput,
    ParameterValueInput,
    UpdateDeploymentInput,
    deployment_config_input_to_dict,
    parameter_inputs_to_dict,
    update_deployment_input_to_dict,
)
from styrmin_backend.api.definitions.environment.inputs import (
    UpdateEnvironmentInput,
    update_environment_input_to_dict,
)
from styrmin_backend.api.definitions.environment.model import Environment
from styrmin_backend.api.definitions.user.model import (
    CreateGroupInput,
    CreateUserInput,
    Group as GroupType,
    LoginResult,
    UpdateGroupInput,
    UpdateUserInput,
    User as UserType,
)
from styrmin_backend import config
from styrmin_backend.api.dependency import SESSION_COOKIE_NAME
from styrmin_backend.db.models import Role
from styrmin_backend.api.definitions.service.model import ServiceNameOverride
from styrmin_backend.api.definitions.task.model import Task
from styrmin_backend.api.scalars import JSON
from styrmin_backend.services.applications import (
    load_application_driver_from_git_repository,
    load_application_driver_from_local_directory,
)
from styrmin_backend.services.auth.login import authenticate
from styrmin_backend.services.auth.password_change import (
    change_password as change_password_service,
)
from styrmin_backend.services.auth.groups import (
    CreateGroupData,
    UpdateGroupData,
    create_group as create_group_service,
    delete_group as delete_group_service,
    update_group as update_group_service,
)
from styrmin_backend.services.auth.users import (
    CreateUserData,
    UpdateUserData,
    create_user as create_user_service,
    delete_user as delete_user_service,
    reset_user_password as reset_user_password_service,
    update_user as update_user_service,
)
from styrmin_backend.services.backup_storage_locations import (
    assign_backup_storage_location as assign_bsl_service,
    create_backup_storage_location as create_bsl_service,
    delete_backup_storage_location as delete_bsl_service,
    unassign_backup_storage_location as unassign_bsl_service,
    update_backup_storage_location as update_bsl_service,
)
from styrmin_backend.services.clusters import (
    create_cluster,
    delete_cluster,
    resolve_cluster,
)
from styrmin_backend.services.deployment import (
    delete_deployment,
    deploy_application,
    update_deployment,
    update_deployment_version,
)
from styrmin_backend.services.environments import (
    create_environment,
    delete_environment,
    resolve_environment,
    update_environment,
)
from styrmin_backend.services.backup.scheduler import (
    create_backup_schedule as create_backup_schedule_service,
    delete_backup_schedule as delete_backup_schedule_service,
    update_backup_schedule as update_backup_schedule_service,
)
from styrmin_backend.services.backup.environment import (
    create_environment_backup as create_environment_backup_service,
    restore_environment_backup as restore_environment_backup_service,
)
from styrmin_backend.services.backup.service import (
    create_backup as create_backup_service,
    create_restore as create_restore_service,
    delete_backup as delete_backup_service,
    resolve_backup_target,
)
from styrmin_backend.services.deployment import get_deployment
from styrmin_backend.services.exceptions import (
    InternalDeploymentError,
    TaskNotFoundError,
)
from styrmin_backend.services.primitives import (
    run_job,
    start_components,
    stop_components,
)
from styrmin_backend.services.deployment_status import (
    report_deployment_statuses,
)
from styrmin_backend.services.pod_status import report_pod_statuses
from styrmin_backend.services.tasks import update_task_state
from styrmin_backend.workflows.dependency import get_manager
from styrmin_backend.workflows.models import PrefectAction


def _requires(role: Role) -> PermissionExtension:
    """Sugar for the per-mutation permission extension. See ADR-017."""
    return PermissionExtension([RequiresRole(role)])


@strawberry.type
class Mutation:
    # login is on the documented allow-list (api/auth/allowlist.py); gating
    # it would lock everyone out before they could authenticate.
    @strawberry.mutation
    async def login(
        self, info: strawberry.Info, username: str, password: str
    ) -> LoginResult:
        uow = info.context["uow"]
        response = info.context["response"]
        user, session, raw_token = await authenticate(
            uow, username=username, password=password
        )
        # Populate the auth context so nested ``LoginResult.user`` field
        # resolvers (role / effectiveRole / active / groups, gated by
        # IsSelfOrRole) see the just-authenticated caller as "self" and
        # resolve their own values. Without this the gate rejects with
        # UNAUTHENTICATED and non-null propagation nulls the whole
        # ``login`` payload — the user can never see their own role.
        info.context["current_user"] = user
        info.context["current_session"] = session
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=raw_token,
            httponly=True,
            # ``secure`` is controlled by STYRMIN_SESSION_COOKIE_SECURE so the
            # local HTTP demo can store the cookie (browsers drop ``Secure``
            # cookies on non-HTTPS, non-localhost origins). Production must
            # keep the default ``True``.
            secure=config.SETTINGS.active_settings.session_cookie_secure,
            samesite="lax",
            path="/",
        )
        return LoginResult(token=raw_token, user=UserType.from_instance(user))

    # logout is on the documented allow-list (api/auth/allowlist.py).
    # ADR-017: a deactivated user must still be able to log out of their
    # existing session — gating logout behind RequiresAuthentication or
    # RequiresRole would defeat deactivation. Idempotent: with no session
    # the call still clears the cookie and returns True.
    @strawberry.mutation
    async def logout(self, info: strawberry.Info) -> bool:
        uow = info.context["uow"]
        response = info.context["response"]
        current_session = info.context.get("current_session")
        if current_session is not None:
            await uow.session.delete(current_session)
            await uow.session.commit()
            logger.info(
                "logout user_id={} session_id={}",
                current_session.user_id,
                current_session.id,
            )
        # Always clear the cookie, regardless of whether a session row was
        # present — idempotent by design.
        response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
        return True

    # changePassword needs only the authenticated baseline (any role can
    # rotate their own password). RequiresRole(READ_ONLY) is the lowest
    # gate the schema-walk completeness test accepts and is always
    # satisfied for an authenticated caller.
    @strawberry.mutation(extensions=[_requires(Role.READ_ONLY)])
    async def change_password(
        self,
        info: strawberry.Info,
        current_password: str,
        new_password: str,
    ) -> bool:
        uow = info.context["uow"]
        current_user = info.context["current_user"]
        current_session = info.context["current_session"]
        # Both are guaranteed non-None by RequiresAuthentication, but we
        # defensively bail rather than UnboundLocalError further down.
        assert current_user is not None and current_session is not None, (
            "RequiresAuthentication should have rejected this request"
        )
        await change_password_service(
            uow.session,
            user=current_user,
            current_password=current_password,
            new_password=new_password,
            calling_session_id=current_session.id,
        )
        return True

    # ------------------------------------------------------------------
    # Admin user mutations (specs/011-admin-user-group-mgmt).
    # All four are admin-only. Service-layer raises ServiceError
    # subclasses with the appropriate error_code; StructuredErrorExtension
    # surfaces them through extensions.code without further mapping here.
    # ------------------------------------------------------------------

    @strawberry.mutation(extensions=[_requires(Role.ADMIN)])
    async def create_user(
        self, info: strawberry.Info, input: CreateUserInput
    ) -> UserType:
        uow = info.context["uow"]
        current_user = info.context["current_user"]
        assert current_user is not None, (
            "RequiresAuthentication should have rejected this request"
        )
        data = CreateUserData(
            username=input.username,
            password=input.password,
            display_name=input.display_name,
            role=Role[input.role.value],
            group_ids=(
                [UUID(str(gid)) for gid in input.group_ids]
                if input.group_ids is not None
                else None
            ),
        )
        user = await create_user_service(uow, input=data, actor_user_id=current_user.id)
        return UserType.from_instance(user)

    @strawberry.mutation(extensions=[_requires(Role.ADMIN)])
    async def update_user(
        self, info: strawberry.Info, id: UUID, input: UpdateUserInput
    ) -> UserType:
        uow = info.context["uow"]
        current_user = info.context["current_user"]
        assert current_user is not None, (
            "RequiresAuthentication should have rejected this request"
        )
        data = UpdateUserData(
            display_name=input.display_name,
            role=Role[input.role.value] if input.role is not None else None,
            active=input.active,
            group_ids=(
                [UUID(str(gid)) for gid in input.group_ids]
                if input.group_ids is not None
                else None
            ),
        )
        user = await update_user_service(
            uow,
            user_id=id,
            input=data,
            actor_user_id=current_user.id,
        )
        return UserType.from_instance(user)

    @strawberry.mutation(extensions=[_requires(Role.ADMIN)])
    async def reset_user_password(
        self,
        info: strawberry.Info,
        user_id: UUID,
        new_password: str,
    ) -> bool:
        uow = info.context["uow"]
        current_user = info.context["current_user"]
        assert current_user is not None, (
            "RequiresAuthentication should have rejected this request"
        )
        return await reset_user_password_service(
            uow,
            user_id=user_id,
            new_password=new_password,
            actor_user_id=current_user.id,
        )

    @strawberry.mutation(extensions=[_requires(Role.ADMIN)])
    async def delete_user(self, info: strawberry.Info, id: UUID) -> bool:
        uow = info.context["uow"]
        current_user = info.context["current_user"]
        assert current_user is not None, (
            "RequiresAuthentication should have rejected this request"
        )
        return await delete_user_service(uow, user_id=id, actor_user_id=current_user.id)

    # ------------------------------------------------------------------
    # Admin group mutations (specs/011-admin-user-group-mgmt).
    # All admin-only; service-layer raises ServiceError subclasses with
    # the appropriate error_code which StructuredErrorExtension surfaces
    # through extensions.code unchanged.
    # ------------------------------------------------------------------

    @strawberry.mutation(extensions=[_requires(Role.ADMIN)])
    async def create_group(
        self, info: strawberry.Info, input: CreateGroupInput
    ) -> GroupType:
        uow = info.context["uow"]
        current_user = info.context["current_user"]
        assert current_user is not None, (
            "RequiresAuthentication should have rejected this request"
        )
        data = CreateGroupData(
            name=input.name,
            role=Role[input.role.value],
            member_ids=(
                [UUID(str(mid)) for mid in input.member_ids]
                if input.member_ids is not None
                else None
            ),
        )
        group = await create_group_service(
            uow, input=data, actor_user_id=current_user.id
        )
        return GroupType.from_instance(group)

    @strawberry.mutation(extensions=[_requires(Role.ADMIN)])
    async def update_group(
        self, info: strawberry.Info, id: UUID, input: UpdateGroupInput
    ) -> GroupType:
        uow = info.context["uow"]
        current_user = info.context["current_user"]
        assert current_user is not None, (
            "RequiresAuthentication should have rejected this request"
        )
        data = UpdateGroupData(
            name=input.name,
            role=Role[input.role.value] if input.role is not None else None,
            member_ids=(
                [UUID(str(mid)) for mid in input.member_ids]
                if input.member_ids is not None
                else None
            ),
        )
        group = await update_group_service(
            uow,
            group_id=id,
            input=data,
            actor_user_id=current_user.id,
        )
        return GroupType.from_instance(group)

    @strawberry.mutation(extensions=[_requires(Role.ADMIN)])
    async def delete_group(self, info: strawberry.Info, id: UUID) -> bool:
        uow = info.context["uow"]
        current_user = info.context["current_user"]
        assert current_user is not None, (
            "RequiresAuthentication should have rejected this request"
        )
        return await delete_group_service(
            uow, group_id=id, actor_user_id=current_user.id
        )

    @strawberry.mutation(extensions=[_requires(Role.ADMIN)])
    async def create_cluster(
        self, info: strawberry.Info, name: str = "default", config: JSON | None = None
    ) -> Cluster | None:
        uow = info.context["uow"]
        cluster = await create_cluster(uow=uow, name=name, config=config)
        return Cluster.from_instance(cluster)

    @strawberry.mutation(extensions=[_requires(Role.ADMIN)])
    async def delete_cluster(
        self,
        info: strawberry.Info,
        cluster_id: UUID | None = None,
        cluster_name: str | None = None,
    ) -> str | None:
        uow = info.context["uow"]
        cluster = await resolve_cluster(
            uow, cluster_id=cluster_id, cluster_name=cluster_name
        )
        await delete_cluster(cluster_id=cluster.id, uow=uow)
        return "Cluster deleted"

    @strawberry.mutation(extensions=[_requires(Role.READ_WRITE)])
    async def create_environment(
        self,
        name: str,
        info: strawberry.Info,
        cluster_id: UUID | None = None,
        cluster_name: str | None = None,
        config: JSON | None = None,
    ) -> Environment | None:
        uow = info.context["uow"]
        cluster = await resolve_cluster(
            uow, cluster_id=cluster_id, cluster_name=cluster_name
        )
        environment = await create_environment(
            name=name, cluster_id=cluster.id, config=config, uow=uow
        )
        return Environment.from_instance(environment)

    @strawberry.mutation(extensions=[_requires(Role.ADMIN)])
    async def update_environment(
        self,
        environment_id: UUID,
        info: strawberry.Info,
        input: UpdateEnvironmentInput,
    ) -> Environment | None:
        """Update an environment's config with a typed ``UpdateEnvironmentInput``.

        Triggers a redeploy fanout: every non-tombstoned, non-internal
        deployment in the environment receives a fresh ``ApplicationInstance``
        version and a redeploy ``Task``. See
        ``specs/009-environment-update/contracts/graphql.md`` §2.

        The typed input is converted to a plain dict (``None``-valued
        fields omitted to express full-replacement semantics) and forwarded
        to the service-layer ``update_environment``, which runs the
        env-var pre-validation ahead of full Pydantic validation so typed
        error codes (``INVALID_ENV_VAR_NAME`` etc.) reach the GraphQL
        boundary intact.
        """
        uow = info.context["uow"]
        config_dict = update_environment_input_to_dict(input)
        environment = await update_environment(
            environment_id=environment_id,
            uow=uow,
            config=config_dict,
        )
        return Environment.from_instance(environment)

    @strawberry.mutation(extensions=[_requires(Role.ADMIN)])
    async def delete_environment(
        self,
        info: strawberry.Info,
        environment_id: UUID | None = None,
        environment_name: str | None = None,
        cluster_id: UUID | None = None,
        cluster_name: str | None = None,
    ) -> str | None:
        uow = info.context["uow"]
        environment = await resolve_environment(
            uow,
            environment_id=environment_id,
            environment_name=environment_name,
            cluster_id=cluster_id,
            cluster_name=cluster_name,
        )
        await delete_environment(environment_id=environment.id, uow=uow)
        return "Environment deleted"

    @strawberry.mutation(extensions=[_requires(Role.ADMIN)])
    async def create_backup_storage_location(
        self,
        name: str,
        endpoint: str,
        bucket: str,
        region: str,
        access_key_id: str,
        secret_access_key: str,
        info: strawberry.Info,
    ) -> BackupStorageLocationType | None:
        uow = info.context["uow"]
        bsl = await create_bsl_service(
            name=name,
            endpoint=endpoint,
            bucket=bucket,
            region=region,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            uow=uow,
        )
        return BackupStorageLocationType.from_instance(bsl)

    @strawberry.mutation(extensions=[_requires(Role.ADMIN)])
    async def update_backup_storage_location(
        self,
        backup_storage_location_id: UUID,
        info: strawberry.Info,
        name: str | None = None,
        endpoint: str | None = None,
        bucket: str | None = None,
        region: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
    ) -> BackupStorageLocationType | None:
        uow = info.context["uow"]
        bsl = await update_bsl_service(
            backup_storage_location_id=backup_storage_location_id,
            uow=uow,
            name=name,
            endpoint=endpoint,
            bucket=bucket,
            region=region,
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
        )

        # Sync credentials to all clusters where this BSL is deployed
        credentials_changed = access_key_id is not None or secret_access_key is not None
        if credentials_changed and bsl.environments:
            try:
                cluster_ids = {env.cluster_id for env in bsl.environments}
                prefect_manager = get_manager()
                for _cluster_id in cluster_ids:
                    await prefect_manager.run_action(
                        action=PrefectAction.SYNC_BSL_UPDATE_CREDENTIALS,
                        parameters={
                            "bsl_name": bsl.name,
                            "namespace": "styrmin",
                            "access_key_id": bsl.access_key_id,
                            "secret_access_key": bsl.secret_access_key,
                        },
                    )
            except Exception as exc:
                logger.warning(
                    f"Failed to dispatch BSL credentials update workflow for BSL {backup_storage_location_id}",
                    exc_info=exc,
                )

        return BackupStorageLocationType.from_instance(bsl)

    @strawberry.mutation(extensions=[_requires(Role.ADMIN)])
    async def delete_backup_storage_location(
        self,
        backup_storage_location_id: UUID,
        info: strawberry.Info,
    ) -> str | None:
        uow = info.context["uow"]
        await delete_bsl_service(
            backup_storage_location_id=backup_storage_location_id, uow=uow
        )
        return "Backup storage location deleted"

    @strawberry.mutation(extensions=[_requires(Role.ADMIN)])
    async def assign_backup_storage_location(
        self,
        environment_id: UUID,
        backup_storage_location_id: UUID,
        info: strawberry.Info,
    ) -> Environment | None:
        uow = info.context["uow"]

        # Capture previous BSL before reassignment
        old_bsl_id: UUID | None = None
        old_bsl_name: str | None = None
        cluster_id: UUID | None = None
        async with uow:
            env = await uow.environments.get(environment_id)
            if env:
                old_bsl_id = env.backup_storage_location_id
                cluster_id = env.cluster_id
                if old_bsl_id:
                    old_bsl = await uow.backup_storage_locations.get(old_bsl_id)
                    if old_bsl:
                        old_bsl_name = old_bsl.name

        await assign_bsl_service(
            environment_id=environment_id,
            backup_storage_location_id=backup_storage_location_id,
            uow=uow,
        )

        # Dispatch BSL sync flows
        try:
            async with uow:
                env = await uow.environments.get(environment_id)
                bsl = await uow.backup_storage_locations.get(backup_storage_location_id)
                if env and bsl and cluster_id:
                    # Check if this is the first env on the cluster referencing this BSL
                    other_envs_on_cluster = [
                        e
                        for e in bsl.environments
                        if e.cluster_id == cluster_id and e.id != environment_id
                    ]
                    if not other_envs_on_cluster:
                        prefect_manager = get_manager()
                        await prefect_manager.run_action(
                            action=PrefectAction.SYNC_BSL_CREATE,
                            parameters={
                                "bsl_id": str(bsl.id),
                                "bsl_name": bsl.name,
                                "namespace": "styrmin",
                                "bucket": bsl.bucket,
                                "region": bsl.region,
                                "endpoint": bsl.endpoint,
                                "access_key_id": bsl.access_key_id,
                                "secret_access_key": bsl.secret_access_key,
                            },
                        )

                    # Handle reassignment: delete old BSL from cluster if it was the last reference
                    if (
                        old_bsl_id
                        and old_bsl_id != backup_storage_location_id
                        and old_bsl_name
                    ):
                        old_bsl = await uow.backup_storage_locations.get(old_bsl_id)
                        if old_bsl:
                            old_remaining = [
                                e
                                for e in old_bsl.environments
                                if e.cluster_id == cluster_id
                            ]
                            if not old_remaining:
                                prefect_manager = get_manager()
                                await prefect_manager.run_action(
                                    action=PrefectAction.SYNC_BSL_DELETE,
                                    parameters={
                                        "bsl_name": old_bsl_name,
                                        "namespace": "styrmin",
                                    },
                                )
        except Exception as exc:
            logger.warning(
                f"Failed to dispatch BSL sync workflow for environment {environment_id}",
                exc_info=exc,
            )

        from styrmin_backend.services.environments import get_environment

        environment = await get_environment(environment_id=environment_id, uow=uow)
        return Environment.from_instance(environment)

    @strawberry.mutation(extensions=[_requires(Role.ADMIN)])
    async def unassign_backup_storage_location(
        self,
        environment_id: UUID,
        info: strawberry.Info,
    ) -> Environment | None:
        uow = info.context["uow"]

        # Capture current BSL info before unassigning
        bsl_name: str | None = None
        cluster_id: UUID | None = None
        is_last_on_cluster = False
        async with uow:
            env = await uow.environments.get(environment_id)
            if env and env.backup_storage_location_id:
                cluster_id = env.cluster_id
                bsl = await uow.backup_storage_locations.get(
                    env.backup_storage_location_id
                )
                if bsl:
                    bsl_name = bsl.name
                    other_envs_on_cluster = [
                        e
                        for e in bsl.environments
                        if e.cluster_id == cluster_id and e.id != environment_id
                    ]
                    is_last_on_cluster = len(other_envs_on_cluster) == 0

        await unassign_bsl_service(environment_id=environment_id, uow=uow)

        # Delete BSL from cluster if this was the last environment referencing it
        if is_last_on_cluster and bsl_name:
            try:
                prefect_manager = get_manager()
                await prefect_manager.run_action(
                    action=PrefectAction.SYNC_BSL_DELETE,
                    parameters={
                        "bsl_name": bsl_name,
                        "namespace": "styrmin",
                    },
                )
            except Exception as exc:
                logger.warning(
                    f"Failed to dispatch BSL delete workflow for environment {environment_id}",
                    exc_info=exc,
                )

        from styrmin_backend.services.environments import get_environment

        environment = await get_environment(environment_id=environment_id, uow=uow)
        return Environment.from_instance(environment)

    @strawberry.mutation(extensions=[_requires(Role.ADMIN)])
    async def load_local_application_driver_version(
        self, path: str, info: strawberry.Info
    ) -> ApplicationDriverVersion | None:
        uow = info.context["uow"]
        application = await load_application_driver_from_local_directory(
            path=path, uow=uow
        )
        return ApplicationDriverVersion.from_instance(application)

    @strawberry.mutation(extensions=[_requires(Role.ADMIN)])
    async def load_remote_application_driver_version(
        self, repository_url: str, branch: str, info: strawberry.Info
    ) -> ApplicationDriverVersion | None:
        uow = info.context["uow"]
        application = await load_application_driver_from_git_repository(
            repository_url=repository_url, branch=branch, uow=uow
        )
        return ApplicationDriverVersion.from_instance(application)

    @strawberry.mutation(extensions=[_requires(Role.READ_WRITE)])
    async def deploy(
        self,
        driver: str,
        info: strawberry.Info,
        environment_id: UUID | None = None,
        environment_name: str | None = None,
        cluster_id: UUID | None = None,
        cluster_name: str | None = None,
        version: str | None = None,
        name: str | None = None,
        config: DeploymentConfigInput | None = None,
        parameters: list[ParameterValueInput] | None = None,
        service_name_overrides: list[ServiceNameOverride] | None = None,
        driver_version_id: UUID | None = None,
    ) -> Task | None:
        """Deploy an application in an environment.

        Without ``driverVersionId`` the deployment is bound to the latest
        loaded driver version supporting the resolved application version;
        with it, the binding is pinned to that specific driver version.

        ``config`` / ``parameters`` use the same typed shapes as
        :class:`UpdateDeploymentInput` (``config`` shares the
        ``DeploymentConfigInput`` base, ``parameters`` is the
        ``[ParameterValueInput!]`` list) so the create and update mutations
        accept an identical configuration payload. The typed inputs are
        flattened to the plain dicts ``deploy_application`` expects via the
        shared converters — list-shaped ``env_vars`` / ``components`` /
        ``parameters`` carry typed duplicate-name detection
        (``DUPLICATE_ENV_VAR_NAME`` / ``DUPLICATE_COMPONENT_NAME`` /
        ``DUPLICATE_PARAMETER_NAME``) intact.
        """
        uow = info.context["uow"]
        current_user = info.context["current_user"]
        # RequiresAuthentication + RequiresRole(READ_WRITE) above guarantee a
        # user is present; assert defensively rather than UnboundLocalError
        # if the chain is ever reordered.
        assert current_user is not None, (
            "RequiresAuthentication should have rejected this request"
        )
        environment = await resolve_environment(
            uow,
            environment_id=environment_id,
            environment_name=environment_name,
            cluster_id=cluster_id,
            cluster_name=cluster_name,
        )
        overrides_dict = (
            {o.driver_service_name: o.override_name for o in service_name_overrides}
            if service_name_overrides
            else None
        )
        config_dict = (
            deployment_config_input_to_dict(config) if config is not None else None
        )
        parameters_dict = parameter_inputs_to_dict(parameters)
        task = await deploy_application(
            driver_name=driver,
            version=version,
            environment_id=environment.id,
            deployment_config=config_dict,
            deployment_parameters=parameters_dict,
            deployment_name=name,
            service_name_overrides=overrides_dict,
            uow=uow,
            created_by_user_id=current_user.id,
            driver_version_id=driver_version_id,
        )
        return Task.from_instance(task)

    @strawberry.mutation(extensions=[_requires(Role.READ_WRITE)])
    async def update_deployment(
        self,
        deployment_id: UUID,
        input: UpdateDeploymentInput,
        info: strawberry.Info,
    ) -> Task | None:
        """Update a deployment's config / name / parameters / overrides.

        The typed :class:`UpdateDeploymentInput` is converted to a plain
        dict (``None``-valued fields omitted to express full-replacement
        semantics) and split into the four legacy keyword arguments the
        service-layer ``update_deployment`` accepts. List-shape fields
        (``parameters``, ``service_name_overrides``, ``components``,
        ``env_vars``) are flattened to dicts with typed duplicate-name
        detection by ``update_deployment_input_to_dict`` so codes like
        ``DUPLICATE_PARAMETER_NAME`` / ``DUPLICATE_ENV_VAR_NAME`` /
        ``DUPLICATE_COMPONENT_NAME`` reach the GraphQL boundary intact.
        The ``InternalDeploymentError`` guard runs before conversion so
        internal deployments reject without doing any input work.
        """
        uow = info.context["uow"]
        deployment = await get_deployment(deployment_id=deployment_id, uow=uow)
        if deployment.internal:
            raise InternalDeploymentError()
        payload = update_deployment_input_to_dict(input)
        name = payload.pop("name", None)
        parameters = payload.pop("parameters", None)
        service_name_overrides = payload.pop("service_name_overrides", None)
        # If only legacy kwargs were set, remaining payload is `{}` — pass
        # `None` so the service does not interpret an empty dict as
        # "clear the persisted config" (fix-1 / regression guard).
        deployment_config = payload if payload else None
        task = await update_deployment(
            deployment_id=deployment_id,
            deployment_config=deployment_config,
            deployment_parameters=parameters,
            deployment_name=name,
            service_name_overrides=service_name_overrides,
            uow=uow,
        )
        return Task.from_instance(task) if task is not None else None

    @strawberry.mutation(extensions=[_requires(Role.READ_WRITE)])
    async def delete_deployment(
        self,
        deployment_id: UUID,
        info: strawberry.Info,
    ) -> Task:
        """Request deletion of a deployment.

        Patches the cluster-side StyrminDeployment CR to flip
        ``spec.deletionRequested`` to ``true`` (immutable once true).
        Returns immediately with a born-complete ``DELETE_DEPLOYMENT`` task
        that serves as the timeline audit record. The cluster-side operator
        drives teardown asynchronously; clients observe completion via
        ``Deployment.status`` transitioning to ``DELETED``.
        """
        uow = info.context["uow"]
        deployment = await get_deployment(deployment_id=deployment_id, uow=uow)
        if deployment.internal:
            raise InternalDeploymentError()
        task = await delete_deployment(
            deployment_id=deployment_id,
            uow=uow,
        )
        return Task.from_instance(task)

    @strawberry.mutation(extensions=[_requires(Role.READ_WRITE)])
    async def create_backup(
        self,
        instance_id: UUID,
        info: strawberry.Info,
        name: str | None = None,
    ) -> BackupType | None:
        """Create a new on-demand backup for an instance."""
        uow = info.context["uow"]

        # Step 1: Resolve component backup configs from the instance's driver
        # version. Shared with the environment-level backup fan-out so both
        # produce identical constituent backups.
        (
            deployment_id,
            target_namespace,
            component_configs,
        ) = await resolve_backup_target(instance_id, uow)

        # Step 2: Create backup with resolved configs
        backup = await create_backup_service(
            instance_id=instance_id,
            name=name,
            uow=uow,
            target_namespace=target_namespace,
            component_configs=component_configs,
        )

        # Step 3: Submit workflow
        try:
            if deployment_id:
                prefect_manager = get_manager()
                await prefect_manager.run_action(
                    action=PrefectAction.EXECUTE_BACKUP,
                    parameters={
                        "backup_id": str(backup.id),
                        "deployment_id": str(deployment_id),
                    },
                )
        except Exception as exc:
            logger.warning(
                f"Failed to submit backup workflow for backup {backup.id}, "
                "backup record created but Velero execution not triggered",
                exc_info=exc,
            )

        return BackupType.from_instance(backup)

    @strawberry.mutation(extensions=[_requires(Role.READ_WRITE)])
    async def create_environment_backup(
        self,
        environment_id: UUID,
        info: strawberry.Info,
        name: str | None = None,
    ) -> EnvironmentBackupType:
        """Snapshot an environment and back up every eligible deployment.

        Captures the environment config plus each eligible deployment's
        declared state, then fans out one constituent backup per eligible
        deployment. Returns as soon as the constituents are created and
        dispatched, so the returned ``status`` is normally ``PENDING`` /
        ``IN_PROGRESS`` — or ``COMPLETED`` immediately for an environment with
        no eligible deployments (spec FR-011).

        A per-instance conflict during the fan-out becomes a
        ``constituents[].error`` entry and never fails the mutation (FR-005);
        a second concurrent environment-level operation is rejected with
        ``ALREADY_IN_PROGRESS`` (FR-009).
        """
        uow = info.context["uow"]
        environment_backup = await create_environment_backup_service(
            environment_id=environment_id,
            name=name,
            uow=uow,
        )
        return EnvironmentBackupType.from_instance(environment_backup)

    @strawberry.mutation(extensions=[_requires(Role.ADMIN)])
    async def restore_environment_backup(
        self,
        environment_backup_id: UUID,
        info: strawberry.Info,
    ) -> EnvironmentRestoreType:
        """Restore an environment snapshot in place, in one action.

        Reverts the environment's config to the captured value and restores
        every usable constituent into its still-existing deployment. Every
        constituent that is *not* restored comes back in
        ``skippedConstituents`` with its deployment name and reason — the
        classification is complete in this response (spec FR-006/FR-007).

        No deployment is ever created or deleted (FR-008): topology drift is
        reported, never repaired.

        Requires ``ADMIN`` rather than ``READ_WRITE``: the restore reverts
        ``Environment.config``, which is exactly what ``updateEnvironment``
        does, and granting config mutation by way of a restore to a lower role
        would be a privilege bypass (research.md D7).
        """
        uow = info.context["uow"]
        environment_restore = await restore_environment_backup_service(
            environment_backup_id=environment_backup_id,
            uow=uow,
        )
        return EnvironmentRestoreType.from_instance(environment_restore)

    @strawberry.mutation(extensions=[_requires(Role.READ_WRITE)])
    async def delete_backup(
        self,
        backup_id: UUID,
        info: strawberry.Info,
    ) -> str | None:
        """Delete a backup and its associated data."""
        uow = info.context["uow"]
        await delete_backup_service(backup_id=backup_id, uow=uow)
        return "Backup deleted"

    @strawberry.mutation(extensions=[_requires(Role.READ_WRITE)])
    async def create_restore(
        self,
        backup_id: UUID,
        target_namespace: str,
        info: strawberry.Info,
        target_instance_id: UUID | None = None,
    ) -> RestoreType | None:
        """Create a restore operation from a backup."""
        uow = info.context["uow"]

        restore, deployment_id = await create_restore_service(
            backup_id=backup_id,
            target_namespace=target_namespace,
            target_instance_id=target_instance_id,
            uow=uow,
        )

        try:
            prefect_manager = get_manager()
            await prefect_manager.run_action(
                action=PrefectAction.EXECUTE_RESTORE,
                parameters={
                    "restore_id": str(restore.id),
                    "backup_id": str(backup_id),
                    "deployment_id": str(deployment_id),
                    "target_namespace": target_namespace,
                },
            )
        except Exception as exc:
            logger.warning(
                f"Failed to submit restore workflow for restore {restore.id}, "
                "restore record created but Velero execution not triggered",
                exc_info=exc,
            )

        return RestoreType.from_instance(restore)

    @strawberry.mutation(extensions=[_requires(Role.READ_WRITE)])
    async def create_backup_schedule(
        self,
        deployment_id: UUID,
        name: str,
        cron_expression: str,
        info: strawberry.Info,
        retention_count: int = 10,
        enabled: bool = True,
    ) -> BackupScheduleType | None:
        """Create a new backup schedule for a deployment."""
        uow = info.context["uow"]
        schedule = await create_backup_schedule_service(
            deployment_id=deployment_id,
            name=name,
            cron_expression=cron_expression,
            retention_count=retention_count,
            enabled=enabled,
            uow=uow,
        )
        return BackupScheduleType.from_instance(schedule)

    @strawberry.mutation(extensions=[_requires(Role.READ_WRITE)])
    async def update_backup_schedule(
        self,
        schedule_id: UUID,
        info: strawberry.Info,
        name: str | None = None,
        cron_expression: str | None = None,
        retention_count: int | None = None,
        enabled: bool | None = None,
    ) -> BackupScheduleType | None:
        """Update an existing backup schedule."""
        uow = info.context["uow"]
        schedule = await update_backup_schedule_service(
            schedule_id=schedule_id,
            name=name,
            cron_expression=cron_expression,
            retention_count=retention_count,
            enabled=enabled,
            uow=uow,
        )
        return BackupScheduleType.from_instance(schedule)

    @strawberry.mutation(extensions=[_requires(Role.READ_WRITE)])
    async def delete_backup_schedule(
        self,
        schedule_id: UUID,
        info: strawberry.Info,
    ) -> str | None:
        """Delete a backup schedule."""
        uow = info.context["uow"]
        await delete_backup_schedule_service(schedule_id=schedule_id, uow=uow)
        return "Backup schedule deleted"

    # callback is on the documented allow-list (api/auth/allowlist.py).
    # TODO(#188): replace with service-account auth so it can carry RequiresRole(ADMIN).
    @strawberry.mutation
    async def callback(
        self,
        task_id: UUID,
        state_name: str,
        state_message: str | None,
        state_type: str,
        info: strawberry.Info,
    ) -> CallbackResponse:
        logger.info(
            f"Callback triggered from {task_id} with state {state_name}: {state_message} ({state_type})..."
        )
        uow = info.context["uow"]

        try:
            await update_task_state(
                task_id=task_id,
                state_name=state_name,
                state_message=state_message,
                uow=uow,
            )
        except TaskNotFoundError as e:
            logger.error(f"Task not found: {e}")
            return CallbackResponse(
                message=f"Task not found: {e}",
                success=False,
            )
        return CallbackResponse(
            message=f"Callback triggered from {task_id} with state {state_name}: {state_message} ({state_type})..."
        )

    @strawberry.mutation(extensions=[_requires(Role.READ_WRITE)])
    async def stop_components(
        self,
        deployment_id: UUID,
        components: list[str],
        info: strawberry.Info,
    ) -> Task | None:
        """Stop the components of an application instance."""
        uow = info.context["uow"]
        task = await stop_components(
            deployment_id=deployment_id,
            components=components,
            uow=uow,
        )
        return Task.from_instance(task)

    @strawberry.mutation(extensions=[_requires(Role.READ_WRITE)])
    async def start_components(
        self,
        deployment_id: UUID,
        components: list[str],
        info: strawberry.Info,
    ) -> Task | None:
        """Start the components of an application instance."""
        uow = info.context["uow"]
        task = await start_components(
            deployment_id=deployment_id,
            components=components,
            uow=uow,
        )
        return Task.from_instance(task)

    @strawberry.mutation(extensions=[_requires(Role.READ_WRITE)])
    async def run_job(
        self,
        deployment_id: UUID,
        commands: list[str],
        env: list[JSON],
        image: str,
        info: strawberry.Info,
    ) -> Task | None:
        """Run a job in the context of an application instance."""
        uow = info.context["uow"]
        task = await run_job(
            deployment_id=deployment_id,
            commands=commands,
            env=env,
            image=image,
            uow=uow,
        )
        return Task.from_instance(task)

    @strawberry.mutation(extensions=[_requires(Role.READ_WRITE)])
    async def update_deployment_version(
        self,
        deployment_id: UUID,
        version: str,
        info: strawberry.Info,
        parameters: JSON | None = None,
        driver_version_id: UUID | None = None,
    ) -> Task | None:
        """Update the version of an application instance.

        Without ``driverVersionId`` the deployment is bound to the latest
        loaded driver version supporting ``version``; with it, the binding is
        pinned to that specific driver version.
        """
        uow = info.context["uow"]
        deployment = await get_deployment(deployment_id=deployment_id, uow=uow)
        if deployment.internal:
            raise InternalDeploymentError()
        task = await update_deployment_version(
            deployment_id=deployment_id,
            deployment_parameters=parameters,
            version=version,
            uow=uow,
            driver_version_id=driver_version_id,
        )
        return Task.from_instance(task) if task is not None else None

    # report_pod_statuses is on the documented allow-list (api/auth/allowlist.py).
    # TODO(#188): replace with service-account auth so it can carry RequiresRole(ADMIN).
    @strawberry.mutation
    async def report_pod_statuses(
        self,
        reports: list[DeploymentPodStatusReport],
        info: strawberry.Info,
    ) -> ReportPodStatusesResponse:
        """Report pod statuses from the agent. Upserts pods and removes stale ones."""
        uow = info.context["uow"]

        report_dicts = [
            {
                "deployment_id": report.deployment_id,
                "pods": [
                    {
                        "pod_name": pod.pod_name,
                        "namespace": pod.namespace,
                        "phase": pod.phase.value,
                        "ready": pod.ready,
                        "restart_count": pod.restart_count,
                        "container_statuses": pod.container_statuses,
                        "node_name": pod.node_name,
                        "component_name": pod.component_name,
                        "started_at": pod.started_at,
                    }
                    for pod in report.pods
                ],
            }
            for report in reports
        ]

        total_updated, total_removed = await report_pod_statuses(
            reports=report_dicts,
            uow=uow,
        )

        return ReportPodStatusesResponse(
            success=True,
            message=f"Updated {total_updated} pods, removed {total_removed} stale pods",
            pods_updated=total_updated,
            pods_removed=total_removed,
        )

    # report_deployment_statuses is on the documented allow-list (api/auth/allowlist.py).
    # TODO(#188): replace with service-account auth so it can carry RequiresRole(ADMIN).
    @strawberry.mutation
    async def report_deployment_statuses(
        self,
        reports: list[DeploymentStatusReportInput],
        info: strawberry.Info,
    ) -> ReportDeploymentStatusesResponse:
        """Report deployment statuses from the agent. Upserts status snapshot and updates Deployment state."""
        uow = info.context["uow"]

        report_dicts = [
            {
                "deployment_id": report.deployment_id,
                "instance_id": report.instance_id,
                "phase": report.phase,
                "display_state": report.display_state,
                "message": report.message,
                "conditions": (
                    [
                        {
                            "type": c.type,
                            "status": c.status,
                            "reason": c.reason,
                            "message": c.message,
                            "lastTransitionTime": (
                                c.last_transition_time.isoformat()
                                if c.last_transition_time
                                else None
                            ),
                        }
                        for c in report.conditions
                    ]
                    if report.conditions
                    else None
                ),
                "managed_resource_counts": (
                    {
                        "networkPolicies": report.managed_resource_counts.network_policies,
                        "secrets": report.managed_resource_counts.secrets,
                        "helmReleases": report.managed_resource_counts.helm_releases,
                        "services": report.managed_resource_counts.services,
                        "middlewares": report.managed_resource_counts.middlewares,
                    }
                    if report.managed_resource_counts
                    else None
                ),
            }
            for report in reports
        ]

        statuses_updated, deployments_updated = await report_deployment_statuses(
            reports=report_dicts,
            uow=uow,
        )

        return ReportDeploymentStatusesResponse(
            success=True,
            message=f"Updated {statuses_updated} status snapshots, {deployments_updated} deployment states synced",
            statuses_updated=statuses_updated,
            deployments_updated=deployments_updated,
        )
