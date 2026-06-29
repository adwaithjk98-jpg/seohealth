"""Mint / inspect a durable Instagram Graph token for Model A (business_discovery).

VERIFIED RECIPE (2026-06-29) — business_discovery returns data only when the
token is a **User access token** carrying ALL of these scopes:

    instagram_basic, instagram_manage_insights, pages_read_engagement, ads_read

(`ads_read` is required because the @seo.health Page is owned by a Business
portfolio — "Page role granted via Business Manager".) A *Page* token does NOT
work: `ads_read` is a user-level permission a Page token can't carry. All four
are usable under Standard Access / "Ready for testing" — no App Review needed.

DURABLE TOKEN — two ways to get one for IG_GRAPH_ACCESS_TOKEN:

  1. RECOMMENDED — Business Manager **System User token** (never expires):
       Business Settings -> Users -> System Users -> Add -> Generate New Token
       -> select the SEO Health app -> tick the 4 scopes above -> and make sure
       the @seo.health Page/IG is assigned as an asset to that system user.
     Copy the token (shown once) straight into IG_GRAPH_ACCESS_TOKEN. No refresh
     job ever. This script can still inspect it (pass it as the argument).

  2. QUICK / DEV — long-lived **User token** (~60 days, then must be refreshed):
     this script exchanges a short-lived Explorer token for the long-lived one.

Usage (from the backend/ directory):
    META_APP_SECRET=xxxx python scripts/ig_token.py <SHORT_LIVED_OR_SYSTEM_USER_TOKEN>

It will: exchange short-lived -> long-lived (a no-op for an already-durable
token), then debug the result to print its expiry + scopes, warn about any
missing required scope, and print the exact .env lines to paste.
"""

from __future__ import annotations

import os
import sys

import httpx

GRAPH = "https://graph.facebook.com"
API_VERSION = os.getenv("IG_GRAPH_API_VERSION", "v25.0")
APP_ID = os.getenv("META_APP_ID", "1378304534203823")
APP_SECRET = os.getenv("META_APP_SECRET", "")
IG_USER_ID = os.getenv("IG_GRAPH_USER_ID", "17841413032640533")

REQUIRED_SCOPES = (
    "instagram_basic",
    "instagram_manage_insights",
    "pages_read_engagement",
    "ads_read",
)


def _die(msg: str) -> None:
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(1)


def _get(path: str, params: dict[str, str]) -> dict:
    resp = httpx.get(f"{GRAPH}/{API_VERSION}/{path}", params=params, timeout=30.0)
    data = resp.json()
    if "error" in data:
        err = data["error"]
        _die(f"(#{err.get('code')}) {err.get('message')}")
    return data


def main() -> None:
    if len(sys.argv) != 2:
        _die("pass exactly one argument: a short-lived (or System User) access token")
    if not APP_SECRET:
        _die("set META_APP_SECRET in the environment (App settings -> Basic -> Show)")

    in_token = sys.argv[1].strip()

    # Exchange to long-lived. For an already-durable token (System User /
    # already-long-lived) Graph just hands back an equivalent token — harmless.
    print("1/2  Exchanging for a long-lived user token (no-op if already durable) ...")
    exch = _get(
        "oauth/access_token",
        {
            "grant_type": "fb_exchange_token",
            "client_id": APP_ID,
            "client_secret": APP_SECRET,
            "fb_exchange_token": in_token,
        },
    )
    token = exch.get("access_token") or in_token

    print("2/2  Inspecting token (expiry + scopes) ...\n")
    debug = _get(
        "debug_token",
        {"input_token": token, "access_token": f"{APP_ID}|{APP_SECRET}"},
    )
    info = debug.get("data") or {}
    scopes = set(info.get("scopes") or [])
    expires_at = info.get("expires_at")
    expiry = "never (System User / non-expiring)" if expires_at in (0, None) else f"epoch {expires_at}"
    missing = [s for s in REQUIRED_SCOPES if s not in scopes]

    print("=" * 68)
    print(f"Token type:  {info.get('type')}  |  expires: {expiry}")
    print(f"Scopes:      {', '.join(sorted(scopes)) or '(none)'}")
    if missing:
        print(f"\n⚠️  MISSING required scope(s): {', '.join(missing)}")
        print("    business_discovery will keep returning (#10) until these are present.")
        print("    Re-generate the token with ALL of:", ", ".join(REQUIRED_SCOPES))
    else:
        print("\n✅  All required scopes present — business_discovery should work.")
    print("\nPaste into backend/.env:")
    print("  IG_GRAPH_ENABLED=true")
    print(f"  IG_GRAPH_USER_ID={IG_USER_ID}")
    print(f"  IG_GRAPH_ACCESS_TOKEN={token}")
    print(f"  META_APP_SECRET={APP_SECRET}")
    print("=" * 68)
    if expires_at not in (0, None):
        print(
            "\nNOTE: this token EXPIRES (~60 days). For a set-and-forget server,"
            "\nuse a Business Manager System User token instead (never expires)."
        )
    print("\nAfter pasting, restart the RQ worker, then run an audit on a business"
          "\nthat has an IG handle (or re-run the Nike test).")


if __name__ == "__main__":
    main()
