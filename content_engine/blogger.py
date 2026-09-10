import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from .models import Article


class BloggerError(RuntimeError):
    """Blogger rejected a publication request."""


@dataclass
class BloggerPublisher:
    blog_id: str
    access_token: str
    timeout: float = 30.0

    def publish(self, article: Article) -> str:
        endpoint = f"https://www.googleapis.com/blogger/v3/blogs/{self.blog_id}/posts/"
        payload = json.dumps({"kind": "blogger#post", "title": article.title, "content": article.body}).encode()
        request = urllib.request.Request(
            endpoint, data=payload,
            headers={"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            return str(data["url"])
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as exc:
            raise BloggerError(f"Blogger publication failed: {exc}") from exc
