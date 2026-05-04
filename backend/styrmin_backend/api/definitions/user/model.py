from __future__ import annotations

from uuid import UUID

import strawberry

from styrmin_backend.db.models import User as UserModel


@strawberry.type
class User:
    id: UUID
    username: str
    display_name: str

    @classmethod
    def from_instance(cls, instance: UserModel) -> User:
        return cls(
            id=instance.id,
            username=instance.username,
            display_name=instance.display_name,
        )


@strawberry.type
class LoginResult:
    token: str
    user: User
