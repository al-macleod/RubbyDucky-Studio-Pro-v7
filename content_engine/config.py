import os
from dataclasses import dataclass
from urllib.parse import urlparse


class ConfigError(ValueError):
    """Raised when environment configuration is missing or unsafe."""


def _bool(value: str, name: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be a boolean")


@dataclass(frozen=True)
class EngineConfig:
    provider: str
    provider_url: str
    provider_api_key: str
    blogger_enabled: bool = False
    blogger_blog_id: str = ""
    blogger_access_token: str = ""
    blogger_oauth_client_id: str = ""
    blogger_oauth_redirect_uri: str = "http://127.0.0.1:8765/oauth/blogger/callback"
    adsense_enabled: bool = False
    adsense_publisher_id: str = ""
    adsense_slot_id: str = ""
    request_timeout_seconds: float = 30.0
    max_retries: int = 3
    schedule_interval_seconds: int = 3600

    @classmethod
    def from_env(cls, environ=None) -> "EngineConfig":
        env = os.environ if environ is None else environ
        config = cls(
            provider=env.get("CONTENT_PROVIDER", "openai-compatible").strip(),
            provider_url=env.get("CONTENT_PROVIDER_URL", "").strip(),
            provider_api_key=env.get("CONTENT_PROVIDER_API_KEY", "").strip(),
            blogger_enabled=_bool(env.get("BLOGGER_PUBLISH_ENABLED", "false"), "BLOGGER_PUBLISH_ENABLED"),
            blogger_blog_id=env.get("BLOGGER_BLOG_ID", "").strip(),
            blogger_access_token=env.get("BLOGGER_ACCESS_TOKEN", "").strip(),
            blogger_oauth_client_id=env.get("BLOGGER_OAUTH_CLIENT_ID", "").strip(),
            blogger_oauth_redirect_uri=env.get(
                "BLOGGER_OAUTH_REDIRECT_URI", "http://127.0.0.1:8765/oauth/blogger/callback"
            ).strip(),
            adsense_enabled=_bool(env.get("ADSENSE_ENABLED", "false"), "ADSENSE_ENABLED"),
            adsense_publisher_id=env.get("ADSENSE_PUBLISHER_ID", "").strip(),
            adsense_slot_id=env.get("ADSENSE_SLOT_ID", "").strip(),
            request_timeout_seconds=float(env.get("CONTENT_REQUEST_TIMEOUT", "30")),
            max_retries=int(env.get("CONTENT_MAX_RETRIES", "3")),
            schedule_interval_seconds=int(env.get("CONTENT_SCHEDULE_INTERVAL", "3600")),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not self.provider:
            raise ConfigError("CONTENT_PROVIDER cannot be empty")
        parsed = urlparse(self.provider_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ConfigError("CONTENT_PROVIDER_URL must be an absolute HTTP(S) URL")
        if not self.provider_api_key:
            raise ConfigError("CONTENT_PROVIDER_API_KEY is required")
        if self.request_timeout_seconds <= 0:
            raise ConfigError("CONTENT_REQUEST_TIMEOUT must be greater than zero")
        if not 0 <= self.max_retries <= 10:
            raise ConfigError("CONTENT_MAX_RETRIES must be between 0 and 10")
        if self.schedule_interval_seconds <= 0:
            raise ConfigError("CONTENT_SCHEDULE_INTERVAL must be greater than zero")
        if self.blogger_enabled and (not self.blogger_blog_id or not self.blogger_access_token):
            raise ConfigError("BLOGGER_BLOG_ID and BLOGGER_ACCESS_TOKEN are required when BLOGGER_PUBLISH_ENABLED=true")
        if self.adsense_enabled and not self.adsense_publisher_id:
            raise ConfigError("ADSENSE_PUBLISHER_ID is required when ADSENSE_ENABLED=true")
        redirect = urlparse(self.blogger_oauth_redirect_uri)
        if redirect.scheme != "http" or redirect.hostname not in {"127.0.0.1", "localhost"}:
            raise ConfigError("BLOGGER_OAUTH_REDIRECT_URI must be a localhost HTTP callback")
