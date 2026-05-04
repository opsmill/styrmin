"""Auth resource: login + current_user."""

from __future__ import annotations

from styrmin_sdk._queries import load_query
from styrmin_sdk.graphql._generated.current_user import (
    CurrentUser,
    CurrentUserCurrentUser,
)
from styrmin_sdk.graphql._generated.login import Login, LoginLogin
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

    async def current_user(self) -> CurrentUserCurrentUser | None:
        result = await self._transport.execute(load_query("current_user"))
        self._check_graphql_errors(result)
        validated = CurrentUser.model_validate(result["data"])
        return validated.current_user
