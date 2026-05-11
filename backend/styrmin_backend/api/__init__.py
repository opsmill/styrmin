import strawberry
from strawberry.fastapi import GraphQLRouter

from styrmin_backend.api.auth.extensions import RequiresAuthentication
from styrmin_backend.api.dependency import get_context
from styrmin_backend.api.errors import StructuredErrorExtension
from styrmin_backend.api.logging.request_log import RequestLoggingExtension
from styrmin_backend.api.schema.mutation import Mutation
from styrmin_backend.api.schema.query import Query


def init_graphql_router() -> GraphQLRouter:
    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        # Order matters: RequiresAuthentication runs first so its
        # pre-coded UNAUTHENTICATED errors arrive at StructuredErrorExtension
        # already shaped, and StructuredErrorExtension preserves them.
        # RequestLoggingExtension emits the masked request line at DEBUG
        # before authentication runs — masking is name-based and the line
        # is purely informational, so ordering does not affect either.
        extensions=[
            RequestLoggingExtension,
            RequiresAuthentication,
            StructuredErrorExtension,
        ],
    )

    return GraphQLRouter(schema, context_getter=get_context)  # type: ignore  # Strawberry GraphQLRouter generic params
