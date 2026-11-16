from strawberry.fastapi import GraphQLRouter
from strawberry.schema.config import StrawberryConfig

from styrmin_backend.api.auth.extensions import RequiresAuthentication
from styrmin_backend.api.dependency import get_context
from styrmin_backend.api.errors import StructuredErrorExtension
from styrmin_backend.api.removed_arguments import ExplainRemovedArguments
from styrmin_backend.api.logging.error_log import StyrminSchema
from styrmin_backend.api.logging.request_log import RequestLoggingExtension
from styrmin_backend.api.scalars import SCALAR_MAP
from styrmin_backend.api.schema.mutation import Mutation
from styrmin_backend.api.schema.query import Query


def init_graphql_router() -> GraphQLRouter:
    # StyrminSchema logs the errors without the request document (#573).
    schema = StyrminSchema(
        query=Query,
        mutation=Mutation,
        config=StrawberryConfig(scalar_map=SCALAR_MAP),
        # Order matters: RequiresAuthentication runs first so its
        # pre-coded UNAUTHENTICATED errors arrive at StructuredErrorExtension
        # already shaped, and StructuredErrorExtension preserves them.
        # RequestLoggingExtension emits the masked request line at DEBUG
        # before authentication runs — masking is name-based and the line
        # is purely informational, so ordering does not affect either.
        # ExplainRemovedArguments only changes the validation rules, so its
        # place in the list does not matter.
        extensions=[
            RequestLoggingExtension,
            RequiresAuthentication,
            StructuredErrorExtension,
            ExplainRemovedArguments,
        ],
    )

    return GraphQLRouter(schema, context_getter=get_context)  # type: ignore  # Strawberry GraphQLRouter generic params
