"""Auth resource: login, logout, current_user, change_password."""

from __future__ import annotations

from styrmin_sdk._queries import load_query
from styrmin_sdk.graphql._generated.change_password import ChangePassword
from styrmin_sdk.graphql._generated.current_user import (
    CurrentUser,
    CurrentUserCurrentUser,
)
from styrmin_sdk.graphql._generated.login import Login, LoginLogin
from styrmin_sdk.graphql._generated.logout import Logout
from styrmin_sdk.resources._base import BaseResource


class AuthResource(BaseResource):
    async def login(self, username: str, password: str) -> LoginLogin:
        result = await self._transport.execute(
            load_query("login"),
            {"username": username, "password": password},
        )
        self._check_graphql_errors(result)
        login_result = self._parse(Login, result["data"], "login", LoginLogin)
        self._transport.set_authorization(login_result.token)
        return login_result

    async def logout(self) -> bool:
        """Log out the calling session and clear the in-memory token.

        The server deletes the session row and emits a cookie-clearing
        ``Set-Cookie``; we mirror that on the SDK side by dropping the
        bearer header so subsequent calls are unauthenticated by default.
        """
        result = await self._transport.execute(load_query("logout"))
        self._check_graphql_errors(result)
        validated = Logout.model_validate(result["data"])
        self._transport.set_authorization(None)
        return validated.logout

    async def change_password(self, current_password: str, new_password: str) -> bool:
        """Rotate the calling user's password.

        The calling session is preserved; every other session for the
        user is invalidated server-side. The bearer header on this client
        keeps working — no need to re-login from this caller.
        """
        result = await self._transport.execute(
            load_query("change_password"),
            {"currentPassword": current_password, "newPassword": new_password},
        )
        self._check_graphql_errors(result)
        validated = ChangePassword.model_validate(result["data"])
        return validated.change_password

    async def current_user(self) -> CurrentUserCurrentUser | None:
        result = await self._transport.execute(load_query("current_user"))
        self._check_graphql_errors(result)
        validated = CurrentUser.model_validate(result["data"])
        return validated.current_user
