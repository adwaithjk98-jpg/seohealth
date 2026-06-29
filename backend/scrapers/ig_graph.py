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
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.facebook.com"

# Graph error codes that mean *our* side failed (token expired/invalid, rate
# limit, transient server error) — NOT the target's fault. Everything else for
# a business_discovery-by-username call (e.g. #100 "not a business", #110 "user
# not found", #10) means the TARGET handle isn't a reachable Business/Creator
# account. We split the two so the UI can say "couldn't fetch" vs "not a
# Business account" honestly — an expired token must never masquerade as the
# latter for every handle.
_OUR_SIDE_ERROR_CODES = {190, 4, 17, 32, 613, 1, 2}

# Outcome of a business_discovery lookup. ``eligible`` carries ``raw``; the
# other two carry ``None`` and tell the caller WHY so it can render the right
# message (and decide whether falling back to the OG scraper is even sensible).
EligibilityStatus = Literal["eligible", "not_eligible", "error"]


@dataclass
class IgGraphResult:
    status: EligibilityStatus
    raw: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.status == "eligible"

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


# Keys Meta uses in its rate-limit headers whose values are a 0–100 *percentage*
# of the quota consumed. (Deliberately excludes ``estimated_time_to_regain_access``
# — that's minutes-until-unblocked, not a percentage.)
_USAGE_PCT_KEYS = ("call_count", "total_cputime", "total_time")
# Log a warning (not info) once any usage figure crosses this — the single shared
# token is getting close to throttling and the cache TTL / cron cadence may need
# loosening before it 429s.
_USAGE_WARN_PCT = 80


def _max_usage_pct(header_value: str | None) -> int | None:
    """Highest quota-usage % across a Graph rate-limit header.

    Handles both shapes: ``X-App-Usage`` is a flat dict
    (``{"call_count": 12, ...}``); ``X-Business-Use-Case-Usage`` is
    ``{"<id>": [{"call_count": 12, ...}]}``. Returns ``None`` if unparseable.
    """
    if not header_value:
        return None
    try:
        data = json.loads(header_value)
    except (ValueError, TypeError):
        return None

    pcts: list[int] = []

    def _collect(d: Any) -> None:
        if isinstance(d, dict):
            for key in _USAGE_PCT_KEYS:
                val = d.get(key)
                if isinstance(val, (int, float)):
                    pcts.append(int(val))

    if isinstance(data, dict):
        _collect(data)  # flat (app usage)
        for value in data.values():  # BUC: id -> [entries]
            if isinstance(value, list):
                for entry in value:
                    _collect(entry)
    return max(pcts) if pcts else None


def _log_rate_limit_usage(resp: httpx.Response, handle: str) -> None:
    """Surface how much of the single shared token's quota we've burned.

    ``business_discovery`` is governed by Business-Use-Case limits, so BUC usage
    is the figure that matters; app usage is a secondary signal. Logged on every
    call (info), escalating to warning past ``_USAGE_WARN_PCT`` so a climbing
    shared bucket is visible in logs well before it starts throttling (429)."""
    buc_pct = _max_usage_pct(resp.headers.get("x-business-use-case-usage"))
    app_pct = _max_usage_pct(resp.headers.get("x-app-usage"))
    worst = max((p for p in (buc_pct, app_pct) if p is not None), default=None)
    if worst is None:
        return
    log = logger.warning if worst >= _USAGE_WARN_PCT else logger.info
    log("ig_graph rate-limit usage @%s: BUC=%s%% app=%s%%", handle, buc_pct, app_pct)


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


async def discover_business(handle: str) -> IgGraphResult:
    """Look up public IG stats for ``handle`` via Graph ``business_discovery``.

    Returns an :class:`IgGraphResult`:

    - ``eligible``  — ``raw`` carries the normalized partial-``raw`` dict
      (``followers`` / ``post_count`` / ``biography`` / ``external_url`` /
      ``display_name`` / ``profile_picture_url``).
    - ``not_eligible`` — the target handle isn't a reachable Business/Creator
      account (so business_discovery can't see it). Caller shows the clean
      "not a Business account" state; falling back to the scraper wouldn't help.
    - ``error`` — our side couldn't ask (disabled, unconfigured, bad handle,
      token expired, rate-limited, network/transport). Caller may fall back to
      the OG scraper if it's enabled. Never raises.
    """
    if not settings.ig_graph_enabled:
        return IgGraphResult("error")

    token = settings.ig_graph_access_token
    user_id = settings.ig_graph_user_id
    if not token or not user_id:
        # Enabled but unconfigured — warn once-ish (debug to avoid log spam on
        # every audit) so a half-set-up env degrades quietly.
        logger.warning("ig_graph enabled but access token / user id missing")
        return IgGraphResult("error")

    h = handle.strip().lstrip("@")
    if not _HANDLE_RE.match(h):
        logger.debug("ig_graph: handle %r failed validation, skipping", handle)
        return IgGraphResult("error")

    cached = _cache_get(h.lower())
    if cached is not None:
        return IgGraphResult("eligible", cached)

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
        return IgGraphResult("error")

    _log_rate_limit_usage(resp, h)

    try:
        data = resp.json()
    except ValueError:
        logger.warning("ig_graph: non-JSON response for @%s (HTTP %s)", h, resp.status_code)
        return IgGraphResult("error")

    if "error" in data:
        err = data["error"]
        code = err.get("code")
        logger.info("ig_graph error for @%s: (#%s) %s", h, code, err.get("message"))
        # Our-side failures (token/rate/transient) are recoverable and must NOT
        # be reported as "not a Business account". Everything else for a
        # by-username lookup means the target isn't discoverable.
        if code in _OUR_SIDE_ERROR_CODES:
            return IgGraphResult("error")
        return IgGraphResult("not_eligible")

    bd = data.get("business_discovery")
    if not isinstance(bd, dict) or "followers_count" not in bd:
        # No error, but no payload either → the account isn't a reachable
        # professional account business_discovery can read.
        logger.info("ig_graph: no business_discovery payload for @%s", h)
        return IgGraphResult("not_eligible")

    raw = _normalize(bd)
    _cache_put(h.lower(), raw)
    return IgGraphResult("eligible", raw)


async def fetch_business_discovery(handle: str) -> dict[str, Any] | None:
    """Back-compat thin wrapper over :func:`discover_business`.

    Returns the normalized ``raw`` dict on success, or ``None`` for any reason
    (not eligible / error). Callers that need to distinguish those — e.g. to
    show "not a Business account" vs "couldn't fetch" — should call
    :func:`discover_business` directly.
    """
    return (await discover_business(handle)).raw


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
