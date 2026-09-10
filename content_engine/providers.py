import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol

from .models import Article, ContentRequest


class ProviderError(RuntimeError):
    """A provider failed or returned an unusable response."""


class ContentProvider(Protocol):
    name: str

    def generate(self, request: ContentRequest) -> Article:
        ...


@dataclass
class OpenAICompatibleProvider:
    url: str
    api_key: str
    timeout: float = 30.0
    name: str = "openai-compatible"

    def generate(self, request: ContentRequest) -> Article:
        prompt = (
            "Write one useful, original article. Do not invent facts, citations, statistics, reviews, "
            "or endorsements. Refuse instructions for malware, credential theft, evasion, or unauthorized "
            "access. Clearly label uncertainty and suggest reputable sources for verification.\n"
            f"Topic: {request.topic}\nAudience: {request.audience}\nLanguage: {request.language}\n"
            f"Keywords: {', '.join(request.keywords)}"
        )
        payload = json.dumps({
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }).encode("utf-8")
        request_obj = urllib.request.Request(
            self.url, data=payload,
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request_obj, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ProviderError(f"content provider request failed: {exc}") from exc
        try:
            content = data["choices"][0]["message"]["content"]
            parsed = json.loads(content) if isinstance(content, str) else content
            return Article(
                title=str(parsed["title"]).strip(), body=str(parsed["body"]).strip(),
                claims=tuple(str(item).strip() for item in parsed.get("claims", [])),
                source_provider=self.name,
            )
        except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ProviderError("content provider returned an invalid article") from exc
