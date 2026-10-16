"""Keeps the S3 keys of a backup storage location in a Prefect Secret block.

The server saves the keys before it starts a ``sync-bsl`` flow, and the flow
loads them by the location's id, so the keys are never flow-run parameters
(#497).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from prefect.blocks.system import Secret
from prefect.client.orchestration import get_client
from prefect.exceptions import ObjectNotFound


@dataclass(frozen=True)
class BslCredentials:
    access_key_id: str
    secret_access_key: str


def credentials_block_name(bsl_id: str) -> str:
    """Name the block after the location's id, which a rename does not change."""
    return f"styrmin-bsl-{bsl_id}-credentials"


async def save_bsl_credentials(bsl_id: str, credentials: BslCredentials) -> None:
    """Create or replace the block that holds the location's keys."""
    # Prefect hides a string value in API reads, but returns a dict value in plain text.
    value = json.dumps(asdict(credentials))
    await Secret(value=value).asave(credentials_block_name(bsl_id), overwrite=True)


async def load_bsl_credentials(bsl_id: str) -> BslCredentials:
    """Read the location's keys from its block."""
    secret = await Secret.aload(credentials_block_name(bsl_id))
    return BslCredentials(**json.loads(secret.value.get_secret_value()))


async def delete_bsl_credentials(bsl_id: str) -> None:
    """Delete the location's block, if there is one."""
    async with get_client() as client:
        try:
            document = await client.read_block_document_by_name(
                credentials_block_name(bsl_id),
                block_type_slug="secret",
                include_secrets=False,
            )
        except ObjectNotFound:
            return
        await client.delete_block_document(document.id)
