from fastapi import APIRouter

from styrmin_backend.api.rest.deployments import router as deployments_router


def init_rest_router() -> APIRouter:
    router = APIRouter()
    router.include_router(deployments_router, prefix="/deployments")
    return router
