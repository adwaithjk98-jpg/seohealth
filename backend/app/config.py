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

    # Razorpay — subscription billing (Test Mode for Phase 3).
    # When ``razorpay_key_id`` is empty, the checkout endpoint falls back to a
    # local mock flow that activates the subscription without an external HTTP
    # call. This is the default for dev and for the no-cost prompt-block builds.
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    # Razorpay-dashboard "plan id" we hand to subscriptions.create. Set on a
    # per-environment basis in test mode (e.g. ``plan_NlVQGq0qHy3Mhz``).
    razorpay_paid_plan_id: str = ""
    # Optional webhook secret. When set, /api/subscriptions/webhook verifies
    # the ``X-Razorpay-Signature`` HMAC before applying the event. When empty,
    # the endpoint accepts events without a signature (dev-friendly).
    razorpay_webhook_secret: str = ""
    # Display-only price label for the Billing UI. Razorpay-side pricing is
    # configured on the plan in the Razorpay dashboard.
    paid_plan_price_label: str = "₹399 / month"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
