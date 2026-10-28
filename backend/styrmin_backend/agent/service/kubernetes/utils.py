import json

from styrmin_sdk.driver_format.context.naming import (  # noqa: F401  re-exported (ADR-0089)
    get_kubernetes_reference,
)


def describe_api_answer(
    status: int | None, reason: str | None, body: str | bytes | None
) -> str:
    """Describe an answer of the Kubernetes API that is not a success, on one line.

    Gives the message of the Kubernetes ``Status`` in *body*, else the HTTP
    *reason*, as "the Kubernetes API answered <status>: <message>". Leaves out
    the HTTP headers and the rest of the body, which ``str(ApiException)`` adds.
    """
    try:
        message = json.loads(body or "")["message"]
    except ValueError, TypeError, KeyError:
        message = reason
    return f"the Kubernetes API answered {status}: {message}"
