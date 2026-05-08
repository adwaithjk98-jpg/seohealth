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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
