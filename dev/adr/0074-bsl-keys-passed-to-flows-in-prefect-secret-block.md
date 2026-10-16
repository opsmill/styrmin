# ADR-074: S3 Keys of a Backup Storage Location Passed to Flows in a Prefect Secret Block

**Status**: Accepted
**Date**: 2026-10-16
**Decision-makers**: Fatih Acar
**Source**: [issue #497](https://github.com/opsmill/styrmin/issues/497)
**Related**: [ADR-059](0059-driver-action-api-tokens.md) (action tokens in flow-run job variables),
[ADR-073](0073-kubernetes-objects-named-and-found-by-record-id.md) (objects named after the record id),
[issue #22](https://github.com/opsmill/styrmin/issues/22) (external secrets management)

## Context

The `sync-bsl-create` and `sync-bsl-update-credentials` flows write the S3 access key and secret
key of a backup storage location to a Kubernetes Secret on the cluster. They run as USER flows,
in Jobs that have no database access, so the server must send them the keys. The server passed
the keys as flow-run parameters. The Prefect server stores the parameters of every flow run and
returns them in its UI and API, so anyone who could read flow runs could read the keys, for as
long as Prefect kept the run (#497).

## Decision drivers

- The keys must not be readable from the parameters of a flow run.
- No change to the GraphQL schema, the database schema or the Helm charts.
- The flows run in Jobs that can reach the Prefect API but not the database.

## Considered options

1. Save the keys in a Prefect `Secret` block named after the location's id, and pass only the id;
   the flow loads the keys from the block.
2. Give the flow a short-lived action token (ADR-059), and let it read the keys from a new API
   field or endpoint.
3. Encrypt the keys with a key that the server and the agent share, and pass the encrypted keys
   as parameters.

## Decision

We chose option 1. Before the server starts either flow, `PrefectManager.save_bsl_credentials`
saves the keys in the block `styrmin-bsl-<location id>-credentials`. The flow's task loads them
by the location's id (`workflows/bsl_credentials.py`). Deleting the location deletes the block.
Styrmin already keeps the GitHub tokens of driver sources in Prefect blocks.

The block's value is a JSON string. Prefect 3.8 hides a string value in API reads that do not ask
for secrets, but returns a dict value in plain text.

Option 2 needs an API surface that returns the keys, a role check so that other `READ_WRITE`
sessions cannot call it, and a GraphQL schema change; the token itself is still in the flow run's
job variables. Option 3 needs a new secret in both Helm charts, and a way to distribute and rotate
it.

## Consequences

- Good, because the Prefect UI and the flow-run API no longer show the keys, and Prefect encrypts
  block data in its database.
- Good, because the change is limited to the server and the flows: no migration, no GraphQL
  change, no new configuration.
- Bad, because a caller of the Prefect API can still read the keys by asking for secret values
  (`include_secrets=true`).
- Bad, because the keys stay on the Prefect server for as long as the location exists, instead of
  for as long as Prefect keeps a flow run. A location that is never assigned has no block.
- Bad, because a failed deletion of the block, for example while the Prefect server is down,
  leaves the block behind. The server logs a warning and nothing deletes the block later.
- Flow runs that versions before #497 started keep the keys in their parameters until Prefect
  deletes them.

## Confirmation

- `backend/tests/unit/workflows/test_bsl_sync.py` fails when a sync flow takes `access_key_id` or
  `secret_access_key` as a parameter.
- `backend/tests/unit/workflows/test_bsl_credentials.py` fails when the block value is not a JSON
  string.
- The E2E test `test_renamed_bsl_cluster_objects_follow_the_location_id` reads the location's flow
  runs and its block from the Prefect API and fails when either shows the keys.

## More information

Issue [#22](https://github.com/opsmill/styrmin/issues/22) asks to move all credentials, including
these keys and the GitHub tokens in Prefect blocks, to an external secrets manager. Doing that
would supersede this record.
