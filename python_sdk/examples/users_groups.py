"""Smoke-test script: drive the user lifecycle through ``client.users``.

Mirrors quickstart.md § E for spec 011-admin-user-group-mgmt. Reads the
admin password from ``STYRMIN_ADMIN_PASSWORD`` and runs the full create
→ update → reset-password → deactivate → delete loop against a local
Styrmin server.
"""

from __future__ import annotations

import asyncio
import os

from styrmin_sdk import StyrminClient
from styrmin_sdk.graphql._generated.enums import Role


async def main() -> None:
    server_address = os.environ.get("STYRMIN_SERVER", "http://localhost:8000")
    admin_username = os.environ.get("STYRMIN_ADMIN_USERNAME", "admin")
    admin_password = os.environ["STYRMIN_ADMIN_PASSWORD"]

    async with StyrminClient(server_address=server_address) as client:
        await client.auth.login(admin_username, admin_password)

        alice = await client.users.create(
            username="alice",
            password="hunter22!",
            display_name="Alice",
            role=Role.READ_WRITE,
        )
        print(f"created user: {alice.username} ({alice.id})")

        await client.users.update(alice.id, role=Role.READ_ONLY)
        await client.users.reset_password(alice.id, "new-pass-123")
        await client.users.update(alice.id, active=False)
        await client.users.delete(alice.id)

        print("remaining users:")
        for user in await client.users.list():
            print(f"  - {user.username} ({user.role})")

        print("groups:")
        for group in await client.groups.list():
            print(f"  - {group.name} ({group.role})")


if __name__ == "__main__":
    asyncio.run(main())
