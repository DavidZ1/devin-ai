from __future__ import annotations

import hmac
from collections.abc import Mapping
from typing import Any

import jwt
from starlette.responses import JSONResponse

from .config import Settings


class AuthenticationError(ValueError):
    pass


def resolve_caller(headers: Mapping[str, str], settings: Settings) -> dict[str, str]:
    normalized = {name.casefold(): value for name, value in headers.items()}
    authorization = normalized.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not separator:
        raise AuthenticationError("Missing bearer token")

    matched_key: str | None = None
    for api_key in settings.api_keys:
        if hmac.compare_digest(
            token.encode("utf-8"), api_key.token.encode("utf-8")
        ):
            matched_key = api_key.name
    if matched_key is None:
        raise AuthenticationError("Invalid bearer token")

    caller = {"key": matched_key}
    jwt_token = normalized.get("x-aily-jwt")
    if settings.aily_jwt_secret:
        if jwt_token:
            try:
                claims = jwt.decode(
                    jwt_token,
                    settings.aily_jwt_secret,
                    algorithms=["HS256"],
                    leeway=30,
                    options={"require": ["exp"]},
                )
            except jwt.PyJWTError as exc:
                raise AuthenticationError("Invalid or expired Aily JWT") from exc
            for field in ("user_id", "tenant_id", "email"):
                value = claims.get(field)
                if value is not None:
                    caller[field] = str(value)
        elif settings.aily_jwt_required:
            raise AuthenticationError("Aily JWT is required")
    return caller


class AuthMiddleware:
    def __init__(self, app: Any, settings: Settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http" or scope.get("path") == "/healthz":
            await self.app(scope, receive, send)
            return
        if self.settings.allow_no_auth and not self.settings.api_keys:
            await self.app(scope, receive, send)
            return
        headers = {
            name.decode("latin-1"): value.decode("latin-1")
            for name, value in scope.get("headers", [])
        }
        try:
            resolve_caller(headers, self.settings)
        except AuthenticationError as exc:
            response = JSONResponse({"error": str(exc)}, status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
