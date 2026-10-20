---
title: Python SDK errors
sidebar_position: 4
description: Which exception the Styrmin Python SDK raises for each error code, and how a program reads the details of a refused request.
---

## Python SDK errors

When the Styrmin server refuses a request, it answers with a GraphQL
error. The error has a message and `extensions`: an object that holds
the error `code` and, for some errors, details such as the path of a
refused field. The Python SDK raises an exception that holds both, so a
program can act on the details without parsing the message.

### Exception for each error code

Every exception below is in `styrmin_sdk.exceptions` and is a subclass of
`StyrminAPIError`. The SDK picks the exception from the error code
(`extensions.code`):

| Error code | Exception |
|------------|-----------|
| `NOT_FOUND`, `USER_NOT_FOUND`, `GROUP_NOT_FOUND` | `ResourceNotFoundError` |
| `ALREADY_EXISTS`, `DUPLICATE_USERNAME`, `DUPLICATE_GROUP_NAME` | `ResourceAlreadyExistsError` |
| `DEPLOYMENT_RESTORING` | `DeploymentRestoringError` |
| `UNAUTHENTICATED`, `INVALID_CREDENTIALS` | `StyrminAuthenticationError` |
| `FORBIDDEN` | `StyrminAuthorizationError` |
| Any other code, such as `VALIDATION_ERROR`, or no code | `OperationFailedError` |

The SDK also raises `IncompatibleServerError`, a subclass of
`OperationFailedError`, when the server does not accept an argument that
the SDK sends because the server is older than the SDK. Upgrade the
server to fix it.

An HTTP failure, such as a refused connection, a timeout or a status
other than 2xx, raises `StyrminTransportError` instead. It is not a
`StyrminAPIError`, and it has no error code.

### Attributes of the exception

| Attribute | What it holds |
|-----------|---------------|
| `str(exc)` | The server's message. |
| `typename` | The error code, for example `VALIDATION_ERROR`. It is empty when the error has no code. |
| `extensions` | A dict with all the extensions of the error, `code` included. It is a copy: changing it changes nothing else. |

When the server returns several errors in one response, the exception is
built from the first one.

The SDK raises some of these exceptions itself, without a server error.
For example, it raises `ResourceNotFoundError` when the server returns no
data for a user, a group or a backup storage location. `extensions` then
holds only `code`.
`IncompatibleServerError` has an empty `typename` and empty `extensions`.

### Reading the details of a refused request

The same SDK call can raise `OperationFailedError` for different
refusals, and each refusal gives its own keys. Check for the key you
need, and raise every other error again, so that the other refusals are
not hidden:

```python
from styrmin_sdk.exceptions import OperationFailedError

try:
    await client.environment_clones.create(
        "prod-rehearsal",
        environment_id=source_environment_id,
        deployment_ids=selected_deployment_ids,
    )
except OperationFailedError as refused:
    if "deployments" not in refused.extensions:
        raise
    for entry in refused.extensions["deployments"]:
        print(entry["deployment_name"] or entry["deployment_id"], entry["paths"])
```

[Choosing which deployments come along](../concepts-and-architecture/backups-and-restores.md#choosing-which-deployments-come-along)
describes the `deployments` key of this refusal.

The keys other than `code` are not listed in one place. During the
alpha, they can change between releases, like the rest of the API; see
[Alpha status](../alpha-status.md).

### Refused manifests in `deployments.apply()` and `apply_files()`

`client.deployments.apply()` and `client.deployments.apply_files()`
return an `ApplyOutcome` for each manifest. When the server refuses the
change to an existing deployment, the outcome has `action="failed"` and
holds the details of the error:

| Field | What it holds |
|-------|---------------|
| `failure_reason` | The server's message. For a new deployment, `apply_files()` puts the manifest's path before it. |
| `error_code` | The error code, as `typename` gives it. |
| `error_extensions` | All the extensions of the error, `code` included, as `extensions` gives them. |

When the server refuses a new deployment, `apply()` raises the exception
instead, and `apply_files()` returns a failed outcome with the same
fields. A failure that has no server error, such as a manifest that names
another driver than the existing deployment, gives an empty
`error_extensions`.
