from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./audithealth.db"
    app_env: str = "development"

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
    from_email: str = "Local SEO Health Monitor <onboarding@resend.dev>"

    # Web Push (VAPID). When the keypair is unset (dev default), push sending is
    # a no-op — same "empty = disabled" convention as Resend/Sentry. Generate a
    # pair with ``python scripts/gen_vapid_keys.py`` and set both in prod; the
    # public key is also served to the frontend as the applicationServerKey.
    # ``vapid_subject`` is the ``mailto:`` contact the push services require in
    # the VAPID claims.
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:hello@yourdomain.in"

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
    max_plan_price_label: str = "₹2,500 / month"

    # Path to the standalone ``audit_scraper`` engine (sibling repo). The
    # competitor scraper adapter spawns ``python3 scrape_competitors.py``
    # from this directory for Discovery-Scan-style bulk runs. Defaults to
    # the local dev layout (``~/Desktop/audit_scraper``); override in prod.
    audit_scraper_path: str = "/Users/adwaithjayakrishnan/Desktop/audit_scraper"
    # Python interpreter used to run the scraper. The engine has its own
    # venv (``audit_scraper/venv``) which carries Selenium + chromedriver,
    # so the default points there. Override when deploying.
    audit_scraper_python: str = (
        "/Users/adwaithjayakrishnan/Desktop/audit_scraper/venv/bin/python3"
    )
    # Per-run wall-clock budget for a Discovery Scan subprocess. The
    # scraper is staged and self-throttles, but a stuck Chrome can still
    # hang for hours — this is the last line of defence.
    audit_scraper_timeout_seconds: int = 900

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

    # HTTP rate limiting (slowapi). Limits are per-client-IP. Tunable per env;
    # the defaults are generous enough not to bite a real user but cap abuse.
    rate_limit_enabled: bool = True
    rate_limit_request_link: str = "5/minute"
    rate_limit_create: str = "30/minute"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
