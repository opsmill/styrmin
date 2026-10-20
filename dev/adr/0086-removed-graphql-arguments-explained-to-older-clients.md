# ADR-086: A Client and a Server of Different Versions Say Which One to Upgrade When a GraphQL Argument Was Removed

**Status**: Accepted
**Date**: 2026-10-20
**Decision-makers**: Fatih Acar
**Source**: specs/archive/031-inplace-restore-target/research.md (R-006);
specs/archive/031-inplace-restore-target/pr-notes.md (review finding 8);
[issue #532](https://github.com/opsmill/styrmin/issues/532); [PR #536](https://github.com/opsmill/styrmin/pull/536)
**Related**: [ADR-085](0085-restore-target-derived-from-the-backups-deployment.md) (the removal of
`targetNamespace` and `targetInstanceId` from `createRestore`)

## Context

Before version 1.0, Styrmin removes GraphQL arguments with no deprecation period, as #472 did for
input fields and #532 did for the `targetNamespace` and `targetInstanceId` arguments of
`createRestore` (ADR-085). After such a removal, the client and the server can have different
versions:

- A `styrminctl`, a Python SDK or a web page from before the removal sends the argument. graphql-core
  refuses it during validation with `Unknown argument 'targetNamespace' on field
  'Mutation.createRestore'.`, which does not say that the client is older than the server or what to
  do.
- A client from after the removal does not send the argument. A server from before the removal, where
  the argument is required, refuses the request with `Field 'createRestore' argument
  'targetNamespace' of type 'String!' is required, but it was not provided.`

For the opposite change, a new optional argument, the Python SDK already raises
`IncompatibleServerError` with a message that says to upgrade the server (`load_version` and
`driverDirectory` in #517, `update_version` and `input` in #388; see
[`dev/guidelines/backend/python.md`](../guidelines/backend/python.md#send-a-new-optional-graphql-argument-in-its-own-operation)).

## Decision drivers

- The message names the cause, a client and a server of different versions, and what to do: upgrade
  the side that is older, or reload the web page.
- The server refuses the request before any resolver runs, so nothing is written and no flow run
  starts.
- Any other unknown argument keeps graphql-core's message.
- No new server error code.

## Considered options

1. Keep graphql-core's messages.
2. Keep the removed arguments in the schema with a deprecation reason, and raise a typed error in
   the resolver when a client passes one.
3. Replace graphql-core's validation rule for argument names with a subclass that reports a listed
   message for each removed argument. In the SDK, recognise the older server's "is required" error
   and raise `IncompatibleServerError`.

## Decision

We chose option 3.

- `api/removed_arguments.py` holds `REMOVED_ARGUMENTS`, which maps `(parent type, field, argument)`
  to a message. `KnownArgumentNamesWithRemovalsRule` subclasses graphql-core's
  `KnownArgumentNamesRule`: for a listed argument, it reports the listed message, and for any other
  argument it runs the parent rule.
- The Strawberry extension `ExplainRemovedArguments` replaces `KnownArgumentNamesRule` with the
  subclass in the validation rules of each operation. It is registered in `api/__init__.py`. The
  request is still refused by validation.
- The list holds `targetNamespace` and `targetInstanceId` of `createRestore`. Their message says that
  `createRestore` no longer takes the argument, that the client is older than the server, and to
  upgrade `styrminctl` and the Python SDK or reload the web page.
- `BackupResource.create_restore` in the Python SDK recognises the error that a server from before
  #532 returns, which starts with `Field 'createRestore' argument 'targetNamespace' of type 'String!'
  is required`. It raises `IncompatibleServerError`, whose message says that the server is older
  than the SDK and to upgrade it. `styrminctl backups restore` prints that message.

Option 1 leaves a user who upgraded only one side with an error that does not say what to do. Option
2 keeps arguments that the server no longer uses in the schema, in introspection and in generated
clients, and needs a new error code, which the PRD of #532 rules out.

## Consequences

- Good, because a user whose client and server have different versions is told which side to
  upgrade.
- Good, because the request is still refused during validation, before any resolver runs.
- Bad, because the list is kept by hand. An argument removed without an entry gets graphql-core's
  message.
- Bad, because the subclass reads the field node from the arguments that graphql-core's visitor
  passes to `enter_argument`. A graphql-core release that changes those arguments breaks it.
  `backend/tests/unit/api/test_removed_arguments.py` fails in that case.
- Bad, because the SDK recognises the older server by the text of graphql-core's message. If that
  text differs, the SDK raises its generic error instead.
- The sources do not say when an entry can leave `REMOVED_ARGUMENTS`.

## Confirmation

- `backend/tests/unit/api/test_removed_arguments.py`: a removed argument gets the listed message,
  another unknown argument keeps graphql-core's message, and a request without removed arguments
  runs.
- `test_create_restore_refuses_a_removed_target_argument` in
  `backend/tests/functional/graphql/test_create_restore.py`: the message, no `Restore` row, and no
  flow run started.
- `test_create_restore_on_a_server_from_before_532_raises` in `python_sdk/tests/test_backups.py`.
- The rules for new code are in
  [`dev/guidelines/backend/python.md`](../guidelines/backend/python.md#remove-an-argument-that-released-clients-send)
  and
  [`dev/guidelines/backend/python.md`](../guidelines/backend/python.md#report-an-older-server-that-still-requires-an-argument-the-sdk-no-longer-sends).

## More information

- [`dev/knowledge/backend/api.md`](../knowledge/backend/api.md) describes where the extension sits
  among the error-handling layers.
- The upgrade steps that users read are under "Migration" in `docs/docs/changelog.md`, section "A
  restore lands only in the deployment its backup was taken of".
