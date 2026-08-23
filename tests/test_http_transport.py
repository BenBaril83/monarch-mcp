"""Tests for the optional Streamable HTTP transport and its bearer-token auth gate."""

import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

import server


def _protected_app(token: str) -> Starlette:
    async def ok(request: Request) -> PlainTextResponse:
        return PlainTextResponse("ok")

    app = Starlette(routes=[Route("/mcp", ok)])
    app.add_middleware(server.BearerTokenAuthMiddleware, token=token)
    return app


class TestBearerTokenAuthMiddleware:
    def test_rejects_missing_authorization_header(self) -> None:
        client = TestClient(_protected_app("secret"))
        response = client.get("/mcp")
        assert response.status_code == 401

    def test_rejects_wrong_token(self) -> None:
        client = TestClient(_protected_app("secret"))
        response = client.get("/mcp", headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401

    def test_rejects_non_bearer_scheme(self) -> None:
        client = TestClient(_protected_app("secret"))
        response = client.get("/mcp", headers={"Authorization": "Basic secret"})
        assert response.status_code == 401

    def test_accepts_matching_token(self) -> None:
        client = TestClient(_protected_app("secret"))
        response = client.get("/mcp", headers={"Authorization": "Bearer secret"})
        assert response.status_code == 200


class TestBuildHttpApp:
    def test_adds_auth_middleware_when_token_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv(server.MCP_HTTP_AUTH_TOKEN_ENV, "secret")

        app = server.build_http_app()

        assert any(mw.cls is server.BearerTokenAuthMiddleware for mw in app.user_middleware)

    def test_no_auth_middleware_when_token_unset(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv(server.MCP_HTTP_AUTH_TOKEN_ENV, raising=False)

        app = server.build_http_app()

        assert not any(mw.cls is server.BearerTokenAuthMiddleware for mw in app.user_middleware)
