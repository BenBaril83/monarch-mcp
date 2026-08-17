"""Tests for the interactive authentication tools and secure session storage.

monarch_login / monarch_login_with_cookies / monarch_logout / check_auth_status
are the escape hatch for when the env-var (MONARCH_EMAIL/MONARCH_PASSWORD) login
in initialize_client() can't complete headlessly — a Cloudflare CAPTCHA gate, or
an MFA/emailed one-time code with no MONARCH_MFA_SECRET configured.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from monarchmoney import CaptchaRequiredException, LoginFailedException, RequireMFAException

import server


class NoElicitContext:
    """Stands in for a client that doesn't support MCP elicitation."""


def elicit_result(action: str, data: object | None = None) -> SimpleNamespace:
    return SimpleNamespace(action=action, data=data)


class TestMonarchLogin:
    @pytest.mark.asyncio
    async def test_no_elicit_support(self) -> None:
        result = await server.monarch_login(NoElicitContext())  # type: ignore[arg-type]
        assert result.success is False
        assert "elicitation" in result.message.lower()

    @pytest.mark.asyncio
    async def test_login_cancelled(self) -> None:
        ctx = MagicMock()
        ctx.elicit = AsyncMock(return_value=elicit_result("decline"))
        result = await server.monarch_login(ctx)
        assert result.success is False
        assert "cancelled" in result.message.lower()

    @pytest.mark.asyncio
    async def test_login_succeeds_without_mfa(self) -> None:
        ctx = MagicMock()
        ctx.elicit = AsyncMock(
            return_value=elicit_result("accept", server.LoginForm(email="user@example.com", password="hunter2"))
        )

        original_client, original_state = server.mm_client, server.auth_state
        try:
            with (
                patch("server.MonarchMoney") as mock_mm_class,
                patch("server.save_session_secure") as mock_save,
            ):
                mock_client = AsyncMock()
                mock_mm_class.return_value = mock_client

                result = await server.monarch_login(ctx)

            assert result.success is True
            assert mock_client.login.called
            assert mock_save.called
            assert server.mm_client is mock_client
            assert server.auth_state == server.AuthState.AUTHENTICATED
        finally:
            server.mm_client, server.auth_state = original_client, original_state

    @pytest.mark.asyncio
    async def test_login_completes_mfa_challenge(self) -> None:
        ctx = MagicMock()
        ctx.elicit = AsyncMock(
            side_effect=[
                elicit_result("accept", server.LoginForm(email="user@example.com", password="hunter2")),
                elicit_result("accept", server.MFACodeForm(code="123456")),
            ]
        )

        original_client, original_state = server.mm_client, server.auth_state
        try:
            with (
                patch("server.MonarchMoney") as mock_mm_class,
                patch("server.save_session_secure"),
            ):
                mock_client = AsyncMock()
                mock_client.login.side_effect = RequireMFAException("MFA required")
                mock_mm_class.return_value = mock_client

                result = await server.monarch_login(ctx)

            assert result.success is True
            mock_client.multi_factor_authenticate.assert_called_once_with("user@example.com", "hunter2", "123456")
        finally:
            server.mm_client, server.auth_state = original_client, original_state

    @pytest.mark.asyncio
    async def test_login_blocked_by_captcha(self) -> None:
        ctx = MagicMock()
        ctx.elicit = AsyncMock(
            return_value=elicit_result("accept", server.LoginForm(email="user@example.com", password="hunter2"))
        )

        with patch("server.MonarchMoney") as mock_mm_class:
            mock_client = AsyncMock()
            mock_client.login.side_effect = CaptchaRequiredException("blocked")
            mock_mm_class.return_value = mock_client

            result = await server.monarch_login(ctx)

        assert result.success is False
        assert "monarch_login_with_cookies" in result.message

    @pytest.mark.asyncio
    async def test_login_failed_credentials(self) -> None:
        ctx = MagicMock()
        ctx.elicit = AsyncMock(
            return_value=elicit_result("accept", server.LoginForm(email="user@example.com", password="wrong"))
        )

        with patch("server.MonarchMoney") as mock_mm_class:
            mock_client = AsyncMock()
            mock_client.login.side_effect = LoginFailedException("bad credentials")
            mock_mm_class.return_value = mock_client

            result = await server.monarch_login(ctx)

        assert result.success is False
        assert "bad credentials" in result.message


class TestMonarchLoginWithCookies:
    @pytest.mark.asyncio
    async def test_no_elicit_support(self) -> None:
        result = await server.monarch_login_with_cookies(NoElicitContext())  # type: ignore[arg-type]
        assert result.success is False

    @pytest.mark.asyncio
    async def test_empty_cookie_value(self) -> None:
        ctx = MagicMock()
        ctx.elicit = AsyncMock(return_value=elicit_result("accept", server.CookieForm(cookie_header="   ")))
        result = await server.monarch_login_with_cookies(ctx)
        assert result.success is False
        assert "empty" in result.message.lower()

    @pytest.mark.asyncio
    async def test_cookie_login_succeeds(self) -> None:
        ctx = MagicMock()
        ctx.elicit = AsyncMock(
            return_value=elicit_result("accept", server.CookieForm(cookie_header="session_id=abc; csrftoken=def"))
        )

        original_client, original_state = server.mm_client, server.auth_state
        try:
            with (
                patch("server.MonarchMoney") as mock_mm_class,
                patch("server.save_session_secure") as mock_save,
            ):
                mock_client = AsyncMock()
                mock_mm_class.return_value = mock_client

                result = await server.monarch_login_with_cookies(ctx)

            assert result.success is True
            assert mock_client.login_with_cookies.called
            assert mock_save.called
        finally:
            server.mm_client, server.auth_state = original_client, original_state

    @pytest.mark.asyncio
    async def test_cookie_login_fails(self) -> None:
        ctx = MagicMock()
        ctx.elicit = AsyncMock(
            return_value=elicit_result("accept", server.CookieForm(cookie_header="not_a_real_cookie"))
        )

        with patch("server.MonarchMoney") as mock_mm_class:
            mock_client = AsyncMock()
            mock_client.login_with_cookies.side_effect = LoginFailedException("missing required cookies")
            mock_mm_class.return_value = mock_client

            result = await server.monarch_login_with_cookies(ctx)

        assert result.success is False
        assert "missing required cookies" in result.message


class TestMonarchLogoutAndStatus:
    @pytest.mark.asyncio
    async def test_logout_clears_session(self) -> None:
        with patch("server.clear_session") as mock_clear:
            result = await server.monarch_logout()
        assert result.success is True
        assert mock_clear.called

    @pytest.mark.asyncio
    async def test_check_auth_status_when_authenticated(self) -> None:
        # The autouse baseline fixture already authenticates mm_client.
        result = await server.check_auth_status()
        assert result.success is True
        assert "authenticated" in result.message.lower()

    @pytest.mark.asyncio
    async def test_check_auth_status_with_saved_session(self) -> None:
        original_client, original_state = server.mm_client, server.auth_state
        try:
            server.mm_client = None
            server.auth_state = server.AuthState.NOT_INITIALIZED
            with patch("server.has_saved_session", return_value=True):
                result = await server.check_auth_status()
            assert result.success is True
            assert "saved session" in result.message.lower()
        finally:
            server.mm_client, server.auth_state = original_client, original_state

    @pytest.mark.asyncio
    async def test_check_auth_status_when_not_authenticated(self) -> None:
        original_client, original_state = server.mm_client, server.auth_state
        try:
            server.mm_client = None
            server.auth_state = server.AuthState.NOT_INITIALIZED
            with patch("server.has_saved_session", return_value=False):
                result = await server.check_auth_status()
            assert result.success is False
            assert "monarch_login" in result.message
        finally:
            server.mm_client, server.auth_state = original_client, original_state


class TestKeyringAvailability:
    def test_unavailable_when_keyring_not_installed(self) -> None:
        with patch.dict("sys.modules", {"keyring": None}):
            assert server._keyring_available() is False

    def test_unavailable_when_backend_probe_fails(self) -> None:
        fake_keyring = MagicMock()
        fake_keyring.set_password.side_effect = Exception("no backend")
        with patch.dict("sys.modules", {"keyring": fake_keyring}):
            assert server._keyring_available() is False

    def test_available_when_probe_round_trips(self) -> None:
        fake_keyring = MagicMock()
        fake_keyring.get_password.return_value = "1"
        with patch.dict("sys.modules", {"keyring": fake_keyring}):
            assert server._keyring_available() is True


class TestSecureSessionFileFallback:
    """These exercise the file-fallback path; the sandbox test env has no real keyring backend."""

    def test_save_and_load_round_trip(self) -> None:
        client = server.MonarchMoney(token="tok_abc123")

        with patch("server._keyring_available", return_value=False):
            server.save_session_secure(client)
            assert server.has_saved_session() is True

            loaded = server.load_session_secure()

        assert loaded is not None
        assert loaded.token == "tok_abc123"

    def test_load_returns_none_when_nothing_saved(self) -> None:
        with patch("server._keyring_available", return_value=False):
            assert server.load_session_secure() is None
            assert server.has_saved_session() is False
