import json
import logging
import time
from dataclasses import dataclass

from .blogger import BloggerPublisher
from .config import EngineConfig
from .models import Article, ContentRequest
from .providers import ContentProvider, OpenAICompatibleProvider, ProviderError
from .safety import validate_article, validate_request


class ContentEngineError(RuntimeError):
    """Generation failed after retry policy or policy validation."""


class JsonLogFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({"level": record.levelname, "event": record.getMessage()})


def configure_logging(logger=None) -> logging.Logger:
    configured = logger or logging.getLogger("content_engine")
    if not configured.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JsonLogFormatter())
        configured.addHandler(handler)
    configured.setLevel(logging.INFO)
    return configured


@dataclass
class ContentEngine:
    config: EngineConfig
    provider: ContentProvider | None = None
    publisher: BloggerPublisher | None = None
    logger: logging.Logger | None = None

    def __post_init__(self):
        self.config.validate()
        self.provider = self.provider or OpenAICompatibleProvider(
            self.config.provider_url, self.config.provider_api_key, self.config.request_timeout_seconds
        )
        self.logger = self.logger or configure_logging()
        if self.config.blogger_enabled:
            self.publisher = self.publisher or BloggerPublisher(
                self.config.blogger_blog_id, self.config.blogger_access_token, self.config.request_timeout_seconds
            )

    def run(self, request: ContentRequest, publish=None) -> Article:
        validate_request(request)
        article = self._generate_with_retry(request)
        validate_article(article)
        should_publish = self.config.blogger_enabled if publish is None else publish
        if should_publish:
            if self.publisher is None:
                raise ContentEngineError("Blogger publishing is enabled but not configured")
            url = self.publisher.publish(article)
            article = Article(**{**article.__dict__, "blogger_url": url})
            self.logger.info("article_published")
        else:
            self.logger.info("article_generated_publish_disabled")
        return article

    def preview(self, request: ContentRequest) -> Article:
        """Generate and validate content without any publication side effect."""
        return self.run(request, publish=False)

    def publish(self, article: Article) -> Article:
        """Publish an already reviewed article when publishing is enabled."""
        validate_article(article)
        if not self.config.blogger_enabled or self.publisher is None:
            raise ContentEngineError("publishing is disabled or Blogger is not configured")
        url = self.publisher.publish(article)
        self.logger.info("article_published")
        return Article(**{**article.__dict__, "blogger_url": url})

    def _generate_with_retry(self, request: ContentRequest) -> Article:
        attempts = self.config.max_retries + 1
        for attempt in range(attempts):
            try:
                self.logger.info("article_generation_attempt_%d", attempt + 1)
                return self.provider.generate(request)
            except ProviderError as exc:
                if attempt == attempts - 1:
                    raise ContentEngineError("content generation exhausted retries") from exc
                time.sleep(min(2 ** attempt, 8))
        raise ContentEngineError("content generation failed")
