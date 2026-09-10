import re

from .models import Article, ContentRequest


class SafetyError(ValueError):
    """Content violates publication policy."""


_UNSAFE = re.compile(
    r"\b(ransomware|credential\s*steal|keylogger|botnet|bypass\s+authentication|"
    r"exploit\s+without\s+permission|steal\s+(?:a\s+)?passwords?)\b", re.IGNORECASE
)
_SPAM = re.compile(r"(?:buy\s+now|act\s+now|guaranteed\s+income|click\s+here).{0,80}", re.IGNORECASE)


def validate_request(request: ContentRequest) -> None:
    if not request.topic.strip() or len(request.topic.strip()) > 240:
        raise SafetyError("topic must be between 1 and 240 characters")
    if _UNSAFE.search(request.topic):
        raise SafetyError("topic requests harmful or unauthorized cyber activity")


def validate_article(article: Article) -> None:
    if not article.title or not article.body:
        raise SafetyError("provider returned an empty title or body")
    if len(article.title) > 180 or len(article.body) > 100_000:
        raise SafetyError("article exceeds publication size limits")
    if not article.claims:
        raise SafetyError("article must identify claims for human verification")
    if _UNSAFE.search(f"{article.title}\n{article.body}"):
        raise SafetyError("article contains harmful or unauthorized cyber guidance")
    if len(_SPAM.findall(article.body)) >= 2:
        raise SafetyError("article contains repetitive promotional spam language")
    if any(not claim for claim in article.claims):
        raise SafetyError("article contains an empty claim")
