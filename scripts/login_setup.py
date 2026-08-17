#!/usr/bin/env python3
"""Standalone script for one-time interactive Monarch Money login.

Run with: uv run scripts/login_setup.py

Use this from a terminal — not through an MCP client — when the server's
non-interactive MONARCH_EMAIL/MONARCH_PASSWORD login can't complete: Monarch's
login can sit behind a Cloudflare CAPTCHA, or require an MFA code or an
emailed one-time code. This establishes a session once and saves it via the
same secure storage (OS keyring, falling back to a permissioned file under
~/.monarch-mcp) that every MCP tool call reuses afterward.

Supports three auth paths, in order of recommendation:

1. Session cookies pasted from a logged-in browser. Sidesteps the Cloudflare
   CAPTCHA gate entirely and works for SSO accounts that can't use password
   login at all.
2. Email and password, with an MFA/emailed-code prompt if Monarch asks for one.
3. A session token pasted directly, for users who already have one.
"""

import asyncio
import getpass
import sys
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from monarchmoney import CaptchaRequiredException, MonarchMoney, RequireMFAException  # noqa: E402

from server import save_session_secure, suppressed_output  # noqa: E402


async def _login_with_cookies() -> MonarchMoney | None:
    print("\n📋 To copy the right cookie string:")
    print("  1. Log in to https://app.monarch.com in Chrome or Firefox")
    print("  2. Open DevTools (F12) → Network tab")
    print("  3. Click any request to api.monarch.com (e.g. any 'graphql' request)")
    print("  4. Scroll to 'Request Headers' and find the 'cookie:' header")
    print("  5. Copy the full value (a long string of key=value; pairs)")
    print()
    cookie_string = getpass.getpass("Paste the Cookie header value: ").strip()
    if not cookie_string:
        print("❌ No cookie string provided. Exiting.")
        return None

    client = MonarchMoney()
    try:
        with suppressed_output():
            await client.login_with_cookies(cookie_string, save_session=False, verify=True)
        print("✅ Cookie login successful")
        return client
    except Exception as e:
        print(f"❌ Cookie login failed: {type(e).__name__}: {e}")
        return None


async def _login_with_password() -> MonarchMoney | None:
    email = input("Email: ").strip()
    password = getpass.getpass("Password: ")

    client = MonarchMoney()
    try:
        with suppressed_output():
            await client.login(email, password, use_saved_session=False, save_session=False)
        print("✅ Login successful")
        return client
    except CaptchaRequiredException as e:
        print(f"❌ {e}")
        print("Re-run this script and choose option 1 (session cookies) instead.")
        return None
    except RequireMFAException:
        code = input("MFA code (or the verification code Monarch emailed you): ").strip()
        if not code:
            print("❌ No code provided. Exiting.")
            return None
        try:
            with suppressed_output():
                await client.multi_factor_authenticate(email, password, code)
            print("✅ MFA/verification successful")
            return client
        except CaptchaRequiredException as e:
            print(f"❌ {e}")
            print("Re-run this script and choose option 1 (session cookies) instead.")
            return None
        except Exception as e:
            print(f"❌ Login failed: {type(e).__name__}: {e}")
            return None
    except Exception as e:
        print(f"❌ Login failed: {type(e).__name__}: {e}")
        return None


def _login_with_token() -> MonarchMoney | None:
    print("\n📋 To get a session token:")
    print("  1. Log in to https://app.monarch.com in Chrome or Firefox")
    print("  2. DevTools (F12) → Application tab → Local Storage → https://app.monarch.com → key 'token'")
    print("  3. Copy the value")
    print()
    token = getpass.getpass("Paste your session token: ").strip()
    if not token:
        print("❌ No token provided. Exiting.")
        return None
    return MonarchMoney(token=token)


async def main() -> None:
    print("\n🏦 Monarch Money — Interactive Login Setup")
    print("=" * 45)
    print("This authenticates you once and saves a session that every")
    print("MCP tool call will reuse — no more re-entering credentials.\n")

    print("How do you sign in to Monarch Money?")
    print("  1) Session cookies from browser   (recommended: sidesteps CAPTCHA, supports SSO)")
    print("  2) Email and password")
    print("  3) Paste a session token directly")
    choice = input("Choice [1]: ").strip() or "1"

    client: MonarchMoney | None
    if choice == "1":
        client = await _login_with_cookies()
    elif choice == "2":
        client = await _login_with_password()
    elif choice == "3":
        client = _login_with_token()
    else:
        print(f"❌ Unrecognized choice: {choice!r}. Exiting.")
        return

    if client is None:
        return

    print("\nTesting connection...")
    try:
        with suppressed_output():
            accounts = await client.get_accounts()
        account_count = len(accounts.get("accounts", [])) if isinstance(accounts, dict) else 0
        print(f"✅ Found {account_count} accounts")
    except Exception as e:
        print(f"❌ Connection test failed: {type(e).__name__}: {e}")
        print("If this looks like 401 Unauthorized, the cookie/token is invalid — re-run this script.")
        return

    try:
        save_session_secure(client)
        print("\n✅ Session saved securely for future tool calls.")
    except Exception as e:
        print(f"❌ Could not save session: {type(e).__name__}: {e}")
        return

    print("\n🎉 Setup complete. Restart your MCP client to pick up the session.")


if __name__ == "__main__":
    asyncio.run(main())
