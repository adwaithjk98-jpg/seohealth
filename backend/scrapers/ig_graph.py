"""Instagram public-stats reader via the Meta Graph API ``business_discovery``.

This is **Model A** of the IG integration (see memory: meta_ig_graph_plan):
ONE server-side token, tied to our own @seo.health IG Business account, reads
the *public* profile stats of ANY IG Business/Creator handle by username. The
account being measured never authorises anything — ``business_discovery`` is
Meta's sanctioned endpoint for exactly this (social-listening tools).

Because every call is made by our own app-admin token, this works under
**Standard Access** — no App Review, no Live mode required. The trade-offs are
operational, not approval-based, and this module owns both:

- **Quota:** every call counts against the single account's ~200/hr rate limit,
  so successful lookups are cached per-handle (``ig_graph_cache_ttl_seconds``)
  to keep re-audits and weekly competitor refreshes from re-hitting Graph.
- **Token longevity:** the token is a long-lived (ideally never-expiring) Page
  token minted out-of-band with ``scripts/ig_token.py`` and dropped into
  ``IG_GRAPH_ACCESS_TOKEN``. If it lapses, calls 401 and we fall back.

Contract: :func:`fetch_business_discovery` returns a normalized partial-``raw``
dict on success, or ``None`` for *any* reason it can't (disabled, no token,
bad handle, account not a public professional account, API/transport error).
``None`` is the caller's cue to fall back to the anonymous OG-tag scraper, so
turning this on can only *add* coverage, never remove it.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import re
import time
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com"

# IG handles are 1–30 chars of letters, digits, '.' and '_'. We validate before
# interpolating into the ``business_discovery.username(<handle>)`` field syntax
# so a hostile handle can't break out of the field expression.
_HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")

# Fields we ask business_discovery for. Note: a *discovered* account exposes
# follower/media counts + bio/website/name, but NOT follows_count (that's only
# readable for the account that owns the token), so ``following`` stays None.
_BD_FIELDS = "followers_count,media_count,biography,website,name,profile_picture_url"

# Positive-only response cache: {handle_lower: (expires_at_epoch, raw_dict)}.
# We deliberately do NOT cache failures — a freshly-public competitor (or the
# business_discovery edge finishing propagation) should be picked up next run.
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _appsecret_proof(token: str) -> str | None:
    """HMAC-SHA256 of the access token, keyed by the app secret.

    Meta recommends sending this with server-side calls so a stolen token is
    useless without the (server-only) app secret. Skipped when no secret is
    configured (dev), since Graph still accepts the call without it.
    """
    secret = settings.meta_app_secret
    if not secret:
        return None
    return hmac.new(secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()


def _cache_get(handle_lower: str) -> dict[str, Any] | None:
    hit = _cache.get(handle_lower)
    if not hit:
        return None
    expires_at, raw = hit
    if expires_at < time.monotonic():
        _cache.pop(handle_lower, None)
        return None
    # Hand back a copy so a caller mutating raw can't poison the cache.
    return dict(raw)


def _cache_put(handle_lower: str, raw: dict[str, Any]) -> None:
    ttl = settings.ig_graph_cache_ttl_seconds
    if ttl <= 0:
        return
    _cache[handle_lower] = (time.monotonic() + ttl, dict(raw))


async def fetch_business_discovery(handle: str) -> dict[str, Any] | None:
    """Read public IG stats for ``handle`` via Graph ``business_discovery``.

    Returns a partial-``raw`` dict the IG scraper merges
    (``followers`` / ``post_count`` / ``biography`` / ``external_url`` /
    ``display_name`` / ``profile_picture_url``), or ``None`` on any failure so
    the caller can fall back to the OG-tag scraper. Never raises.
    """
    if not settings.ig_graph_enabled:
        return None

    token = settings.ig_graph_access_token
    user_id = settings.ig_graph_user_id
    if not token or not user_id:
        # Enabled but unconfigured — warn once-ish (debug to avoid log spam on
        # every audit) so a half-set-up env degrades to the scraper quietly.
        logger.warning("ig_graph enabled but access token / user id missing; using fallback")
        return None

    h = handle.strip().lstrip("@")
    if not _HANDLE_RE.match(h):
        logger.debug("ig_graph: handle %r failed validation, skipping", handle)
        return None

    cached = _cache_get(h.lower())
    if cached is not None:
        return cached

    endpoint = f"{GRAPH_BASE}/{settings.ig_graph_api_version}/{user_id}"
    params: dict[str, str] = {
        "fields": f"business_discovery.username({h}){{{_BD_FIELDS}}}",
        "access_token": token,
    }
    proof = _appsecret_proof(token)
    if proof:
        params["appsecret_proof"] = proof

    try:
        async with httpx.AsyncClient(
            timeout=settings.ig_graph_timeout_seconds,
            headers={"Accept": "application/json"},
        ) as client:
            resp = await client.get(endpoint, params=params)
    except httpx.HTTPError as exc:
        logger.warning("ig_graph request failed for @%s: %s", h, exc)
        return None

    try:
        data = resp.json()
    except ValueError:
        logger.warning("ig_graph: non-JSON response for @%s (HTTP %s)", h, resp.status_code)
        return None

    if "error" in data:
        err = data["error"]
        # (#10) = business_discovery edge not yet propagated / app lacks access;
        # (#100) = the target isn't a reachable public professional account.
        # Both are expected, recoverable conditions → fall back silently-ish.
        logger.info(
            "ig_graph error for @%s: (#%s) %s",
            h,
            err.get("code"),
            err.get("message"),
        )
        return None

    bd = data.get("business_discovery")
    if not isinstance(bd, dict) or "followers_count" not in bd:
        logger.info("ig_graph: no business_discovery payload for @%s", h)
        return None

    raw = _normalize(bd)
    _cache_put(h.lower(), raw)
    return raw


def _normalize(bd: dict[str, Any]) -> dict[str, Any]:
    """Map a business_discovery payload to the IG scraper's ``raw`` vocabulary."""
    followers = bd.get("followers_count")
    posts = bd.get("media_count")
    website = bd.get("website") or None
    return {
        "source": "graph",
        "followers": int(followers) if isinstance(followers, (int, float)) else None,
        "post_count": int(posts) if isinstance(posts, (int, float)) else None,
        "biography": bd.get("biography") or None,
        "external_url": website,
        "display_name": bd.get("name") or None,
        "profile_picture_url": bd.get("profile_picture_url") or None,
    }
