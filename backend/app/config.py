from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./audithealth.db"
    app_env: str = "development"

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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
