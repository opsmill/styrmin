import strawberry
from strawberry.fastapi import GraphQLRouter

from styrmin_backend.api.dependency import get_context
from styrmin_backend.api.errors import StructuredErrorExtension
from styrmin_backend.api.schema.mutation import Mutation
from styrmin_backend.api.schema.query import Query


def init_graphql_router() -> GraphQLRouter:
    schema = strawberry.Schema(
        query=Query,
        mutation=Mutation,
        extensions=[StructuredErrorExtension],
    )

    return GraphQLRouter(schema, context_getter=get_context)  # type: ignore  # Strawberry GraphQLRouter generic params
