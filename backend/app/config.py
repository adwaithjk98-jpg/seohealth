from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./audithealth.db"
    app_env: str = "development"

    # Product brand name — single source of truth for user-facing copy
    # (email subjects/headers, etc.). The frontend's canonical name is
    # "SEO Health"; keep this in sync with it.
    app_name: str = "SEO Health"

    # Redis — used as RQ's transport and (later) the cross-process pub/sub
    # bridge for SSE audit events. Local default points at a loopback Redis
    # with no auth on db 0.
    redis_url: str = "redis://localhost:6379/0"

    # Auth — magic-link + cookie session.
    # Where the magic-link points to (i.e. the frontend origin). The user clicks
    # the link from their email, the frontend page reads the token, and POSTs
    # it back to /api/auth/verify.
    frontend_base_url: str = "http://localhost:5173"
    magic_link_ttl_minutes: int = 15
    session_ttl_days: int = 30
    session_cookie_name: str = "session"
    # In production this should be True (HTTPS-only cookie).
    session_cookie_secure: bool = False

    # Email — Resend transactional sender used for magic-link delivery.
    # When unset, the magic-link sender falls back to printing the link to stdout
    # (dev mode). Both must be set to actually send mail.
    resend_api_key: str = ""
    # Display name should match ``app_name``; the address stays on the Resend
    # sandbox until the seohealth.in sending domain is verified in prod.
    from_email: str = "SEO Health <onboarding@resend.dev>"

    # Web Push (VAPID). When the keypair is unset (dev default), push sending is
    # a no-op — same "empty = disabled" convention as Resend/Sentry. Generate a
    # pair with ``python scripts/gen_vapid_keys.py`` and set both in prod; the
    # public key is also served to the frontend as the applicationServerKey.
    # ``vapid_subject`` is the ``mailto:`` contact the push services require in
    # the VAPID claims.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:hello@seohealth.in"

    # Razorpay — subscription billing (Test Mode for Phase 3).
    # When ``razorpay_key_id`` is empty, the checkout endpoint falls back to a
    # local mock flow that activates the subscription without an external HTTP
    # call. This is the default for dev and for the no-cost prompt-block builds.
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    # Razorpay-dashboard "plan id" we hand to subscriptions.create. Set on a
    # per-environment basis in test mode (e.g. ``plan_NlVQGq0qHy3Mhz``).
    razorpay_paid_plan_id: str = ""
    # Razorpay plan id for the Max (multi-location / agency) tier. Same idea as
    # the Pro plan id above; a separate plan in the Razorpay dashboard.
    razorpay_max_plan_id: str = ""
    # Optional webhook secret. When set, /api/subscriptions/webhook verifies
    # the ``X-Razorpay-Signature`` HMAC before applying the event. When empty,
    # the endpoint accepts events without a signature (dev-friendly).
    razorpay_webhook_secret: str = ""
    # Display-only price labels for the Billing UI. Razorpay-side pricing is
    # configured on the plan in the Razorpay dashboard.
    paid_plan_price_label: str = "₹549 / month"
    max_plan_price_label: str = "₹1,999 / month"

    # Anthropic API key for the competitor-insights phrasing layer. When
    # unset, the insights service falls back to a deterministic sentence
    # so dev workflows don't depend on a paid key.
    anthropic_api_key: str = ""
    # Model used for the insights phrasing layer. Haiku is the cheap +
    # fast tier; the workload (one short summarisation per insight per
    # request) doesn't benefit from a larger model.
    anthropic_insights_model: str = "claude-haiku-4-5-20251001"

    # Founder/admin access. Comma-separated emails that may view /api/admin/*
    # (the founder stats panel). Override in prod via env.
    admin_emails: str = "adwaithjk98@gmail.com"

    # Sentry error monitoring. No-op when empty (dev default). Set the DSN in
    # prod to start capturing exceptions. ``sentry_traces_sample_rate`` controls
    # performance tracing volume — 0 keeps it error-only (free-tier friendly).
    sentry_dsn: str = ""
    sentry_traces_sample_rate: float = 0.0

    # PageSpeed Insights (the Performance / Site-Speed audit pillar). The PSI
    # API works without a key at a low anonymous quota; set a key in prod for
    # the higher per-day quota (Google Cloud console → PageSpeed Insights API).
    # ``strategy`` is ``mobile`` (local-business traffic is mobile-first) or
    # ``desktop``. The timeout is generous because Google runs Lighthouse
    # synchronously and a cold run can take 20–30s.
    pagespeed_api_key: str = ""
    pagespeed_strategy: str = "mobile"
    pagespeed_timeout_seconds: float = 60.0

    # Places API (New) — the Google Cloud API that replaces the Selenium
    # ``maps.py`` scraper (Maps pillar + competitor refresh via Place Details,
    # discovery via Text Search). Key from GCP project "seohealth", restricted
    # to Places API (New). Empty until the maps → Places migration ships; the
    # HTTP client will read this via ``settings.places_api_key``.
    places_api_key: str = ""

    # Instagram Graph API — Model A: ``business_discovery`` reads PUBLIC stats
    # for any IG Business/Creator handle using ONE server-side token (our own
    # @seo.health account). Powers both the user's own IG audit section and
    # competitor IG tracking through ``scrapers.instagram.audit_instagram``,
    # with the anonymous OG-tag scraper as automatic fallback. Works under
    # Standard Access (admin token has a role) — no App Review needed.
    #
    # Disabled by default: flip ``ig_graph_enabled`` on only once a durable
    # token is in ``ig_graph_access_token`` (mint/inspect with scripts/ig_token.py)
    # AND ``business_discovery`` is confirmed returning data. VERIFIED 2026-06-29:
    # needs a USER token (not a Page token) with scopes instagram_basic +
    # instagram_manage_insights + pages_read_engagement + ads_read — all Standard
    # Access, no App Review. Prefer a Business Manager System User token (never
    # expires). See memory: meta_ig_graph_plan. ``ig_graph_user_id`` = @seo.health.
    ig_graph_enabled: bool = False
    ig_graph_access_token: str = ""
    ig_graph_user_id: str = "17841413032640533"
    ig_graph_api_version: str = "v25.0"
    ig_graph_timeout_seconds: float = 12.0
    # Positive-response cache TTL (seconds). Guards the single account's
    # ~200/hr quota against re-audits + weekly competitor refreshes. 0 disables.
    ig_graph_cache_ttl_seconds: float = 21600.0  # 6 hours
    # OG-tag fallback scraper (anonymous GET on instagram.com). DISABLED by
    # default so dev behaves like a server: from a datacenter IP that GET gets
    # rate-limited / CAPTCHA-walled — the exact problem the Graph API migration
    # exists to avoid — so we deliberately don't fall back to it in production.
    # When the Graph read can't cover a handle (target isn't a Business/Creator
    # account), the IG section reports a clean "unavailable" state instead.
    # Flip on ONLY for local debugging on a residential IP; the proper
    # production fallback is a managed scraper (Apify), tracked separately.
    ig_scraper_fallback_enabled: bool = False
    # Meta app credentials. ``meta_app_secret`` (when set) is used at request
    # time for ``appsecret_proof`` and by scripts/ig_token.py to mint/refresh
    # tokens. The app id is public; the secret is server-only — never ship it.
    meta_app_id: str = "1378304534203823"
    meta_app_secret: str = ""

    # HTTP rate limiting (slowapi). Limits are per-client-IP. Tunable per env;
    # the defaults are generous enough not to bite a real user but cap abuse.
    rate_limit_enabled: bool = True
    rate_limit_request_link: str = "5/minute"
    rate_limit_create: str = "30/minute"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
