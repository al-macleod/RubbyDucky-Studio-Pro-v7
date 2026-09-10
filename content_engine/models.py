from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass(frozen=True)
class ContentRequest:
    topic: str
    audience: str = "general readers"
    language: str = "en"
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class Article:
    title: str
    body: str
    claims: tuple[str, ...] = ()
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_provider: str = "unknown"
    blogger_url: Optional[str] = None
