from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from styrmin_backend.api.dependency import get_unit_of_work_dependency
from styrmin_backend.context.models.contexts import GlobalContext
from styrmin_backend.services.context import generate_context_from_deployment_id
from styrmin_backend.services.exceptions import DeploymentNotFoundError
from styrmin_backend.services.unit_of_work import SqlModelUnitOfWork

router = APIRouter()


@router.get("/{deployment_id}/context")
async def get_deployment_context(
    deployment_id: UUID,
    uow: SqlModelUnitOfWork = Depends(get_unit_of_work_dependency),
) -> GlobalContext:
    try:
        return await generate_context_from_deployment_id(
            deployment_id=deployment_id, uow=uow
        )
    except DeploymentNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Deployment {deployment_id} not found",
        )
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Context generation failed: {exc}",
        )
