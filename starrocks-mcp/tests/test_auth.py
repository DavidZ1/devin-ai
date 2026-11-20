from datetime import datetime, timedelta, timezone

import jwt
import pytest
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from starrocks_mcp.auth import AuthMiddleware, resolve_caller
from starrocks_mcp.config import ApiKey, Settings


async def healthz(_request):
    return JSONResponse({"status": "ok"})


async def private(_request):
    return JSONResponse({"status": "authorized"})


def make_client(settings):
    app = Starlette(
        routes=[
            Route("/healthz", healthz),
            Route("/private", private),
        ],
        middleware=[Middleware(AuthMiddleware, settings=settings)],
    )
    return TestClient(app)


def settings(**overrides):
    values = {
        "api_keys": (ApiKey("test-client", "secret-token"),),
        "mcp_transport": "streamable-http",
    }
    values.update(overrides)
    return Settings(**values)


def bearer(token="secret-token"):
    return {"Authorization": f"Bearer {token}"}


def jwt_token(secret, **claims):
    payload = {
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        **claims,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def test_healthz_is_open():
    response = make_client(settings()).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.parametrize("headers", [{}, bearer("wrong-token")])
def test_missing_or_wrong_bearer_is_unauthorized(headers):
    response = make_client(settings()).get("/private", headers=headers)
    assert response.status_code == 401


def test_valid_bearer_passes():
    response = make_client(settings()).get("/private", headers=bearer())
    assert response.status_code == 200
    assert response.json() == {"status": "authorized"}


def test_explicit_no_auth_mode_passes():
    config = settings(api_keys=(), allow_no_auth=True)
    response = make_client(config).get("/private")
    assert response.status_code == 200


def test_valid_jwt_passes_and_caller_has_email():
    secret = "jwt-secret-with-at-least-32-bytes-long"
    claims = {"user_id": "ou_123", "tenant_id": "tenant", "email": "u@example.com"}
    headers = {
        **bearer(),
        "x-aily-jwt": jwt_token(secret, **claims),
    }
    response = make_client(settings(aily_jwt_secret=secret)).get(
        "/private", headers=headers
    )
    assert response.status_code == 200
    assert resolve_caller(headers, settings(aily_jwt_secret=secret)) == {
        "key": "test-client",
        **claims,
    }


@pytest.mark.parametrize(
    "token",
    [
        jwt_token(
            "jwt-secret-with-at-least-32-bytes-long",
            exp=datetime.now(timezone.utc) - timedelta(minutes=1),
            email="expired@example.com",
        ),
        jwt_token(
            "wrong-secret-with-at-least-32-bytes-long",
            exp=datetime.now(timezone.utc) + timedelta(hours=1),
            email="wrong@example.com",
        ),
    ],
)
def test_expired_or_bad_signature_jwt_is_unauthorized(token):
    headers = {**bearer(), "x-aily-jwt": token}
    response = make_client(
        settings(aily_jwt_secret="jwt-secret-with-at-least-32-bytes-long")
    ).get("/private", headers=headers)
    assert response.status_code == 401


def test_required_jwt_missing_is_unauthorized():
    headers = bearer()
    config = settings(
        aily_jwt_secret="jwt-secret-with-at-least-32-bytes-long",
        aily_jwt_required=True,
    )
    response = make_client(config).get("/private", headers=headers)
    assert response.status_code == 401
