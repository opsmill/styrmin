"""Tell a client that sends a removed argument what changed and how to upgrade.

graphql-core refuses an argument the schema does not declare with "Unknown
argument 'x' on field 'T.f'.", which does not say that the server removed it
or that the client is older than the server. For the arguments listed in
``REMOVED_ARGUMENTS``, ``ExplainRemovedArguments`` reports the listed message
instead. The request is still refused by validation, before any resolver runs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from graphql import GraphQLError, KnownArgumentNamesRule
from strawberry.extensions import SchemaExtension

if TYPE_CHECKING:
    from collections.abc import Iterator

    from graphql import ArgumentNode

_CREATE_RESTORE_REMOVED = (
    "createRestore no longer takes the argument {argument}: Styrmin restores a "
    "backup into the deployment it was taken of, so the request names only "
    "backupId (#532). The client that sent this request is older than the "
    "server. Upgrade styrminctl and the Python SDK to the server's version, or "
    "reload the web page."
)

#: ``(parent type, field, argument)`` of each removed argument, and the message
#: that replaces "Unknown argument". ``{argument}`` is the argument's name.
REMOVED_ARGUMENTS: dict[tuple[str, str, str], str] = {
    ("Mutation", "createRestore", "targetNamespace"): _CREATE_RESTORE_REMOVED,
    ("Mutation", "createRestore", "targetInstanceId"): _CREATE_RESTORE_REMOVED,
}


class KnownArgumentNamesWithRemovalsRule(KnownArgumentNamesRule):
    """``KnownArgumentNamesRule`` that explains a removed argument."""

    def enter_argument(self, arg_node: ArgumentNode, *args: Any) -> None:  # noqa: ANN401
        context = self.context
        parent_type = context.get_parent_type()
        if (
            context.get_argument() is None
            and context.get_field_def() is not None
            and parent_type is not None
        ):
            # ``args`` is (key, parent, path, ancestors); the last ancestor is
            # the field node, as in ``KnownArgumentNamesRule``.
            field_name = args[3][-1].name.value
            argument = arg_node.name.value
            message = REMOVED_ARGUMENTS.get((parent_type.name, field_name, argument))
            if message is not None:
                context.report_error(
                    GraphQLError(message.format(argument=argument), arg_node)
                )
                return
        super().enter_argument(arg_node, *args)


class ExplainRemovedArguments(SchemaExtension):
    """Validate argument names with ``KnownArgumentNamesWithRemovalsRule``."""

    def on_operation(self) -> Iterator[None]:
        self.execution_context.validation_rules = tuple(
            KnownArgumentNamesWithRemovalsRule
            if rule is KnownArgumentNamesRule
            else rule
            for rule in self.execution_context.validation_rules
        )
        yield
