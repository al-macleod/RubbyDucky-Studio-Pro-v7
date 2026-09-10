"""Local-only control UI for configuring and safely operating the engine."""

import html
import json
import secrets
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .config import ConfigError, EngineConfig
from .models import ContentRequest
from .pipeline import ContentEngine, ContentEngineError
from .scheduler import IntervalScheduler


_PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>Content Engine Control</title>
<style>body{font:16px system-ui;max-width:900px;margin:2rem auto;padding:0 1rem}
section{border:1px solid #ddd;border-radius:8px;padding:1rem;margin:1rem 0}
label{display:block;margin:.6rem 0}input,textarea{box-sizing:border-box;width:100%;padding:.5rem}
button{padding:.6rem 1rem;margin:.3rem 0}.danger{background:#fee}.muted{color:#666}
pre{white-space:pre-wrap;background:#f6f6f6;padding:1rem}</style></head>
<body><h1>Content Engine Control</h1>
<p class="muted">Local control plane. Credentials are never displayed or persisted by this UI.</p>
<section><h2>Health and configuration</h2><pre id="status">Loading...</pre>
<button onclick="refresh()">Refresh status</button>
<a href="/oauth/blogger/start"><button type="button">Link Blogger account</button></a></section>
<section><h2>Preview / dry run</h2>
<form id="preview"><label>Topic<input name="topic" required maxlength="240"></label>
<label>Audience<input name="audience" value="general readers"></label>
<label>Keywords<input name="keywords" placeholder="comma,separated"></label>
<button>Generate preview (never publishes)</button></form><pre id="result"></pre></section>
<section class="danger"><h2>Explicit publish</h2>
<p>Publishing requires BLOGGER_PUBLISH_ENABLED=true and valid Blogger credentials.</p>
<form id="publish"><label>Approved preview JSON<textarea name="article" required></textarea></label>
<button>Publish explicitly</button></form><pre id="publish-result"></pre></section>
<script>
const statusBox=document.getElementById('status'), previewForm=document.getElementById('preview'),
resultBox=document.getElementById('result'), publishForm=document.getElementById('publish'),
publishResultBox=document.getElementById('publish-result');
async function refresh(){const r=await fetch('/api/status');statusBox.textContent=JSON.stringify(await r.json(),null,2)}
previewForm.onsubmit=async(e)=>{e.preventDefault();const f=new FormData(previewForm);
const r=await fetch('/api/preview',{method:'POST',headers:{'Content-Type':'application/json'},
body:JSON.stringify({topic:f.get('topic'),audience:f.get('audience'),keywords:f.get('keywords').split(',').map(x=>x.trim()).filter(Boolean)})});
resultBox.textContent=JSON.stringify(await r.json(),null,2)}
publishForm.onsubmit=async(e)=>{e.preventDefault();const f=new FormData(publishForm);let article;
try{article=JSON.parse(f.get('article'))}catch(x){publishResultBox.textContent='Invalid JSON';return}
const r=await fetch('/api/publish',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(article)});
publishResultBox.textContent=JSON.stringify(await r.json(),null,2)}
refresh();
</script></body></html>"""


def _mask(value):
    return "configured" if value else "not configured"


class ControlService:
    def __init__(self, config: EngineConfig, engine: ContentEngine):
        self.config = config
        self.engine = engine
        self.scheduler = IntervalScheduler(config.schedule_interval_seconds)
        self.oauth_state = secrets.token_urlsafe(24)

    def status(self):
        try:
            self.config.validate()
            valid, error = True, None
        except ConfigError as exc:
            valid, error = False, str(exc)
        return {
            "config_valid": valid,
            "config_error": error,
            "provider": self.config.provider,
            "provider_api_key": _mask(self.config.provider_api_key),
            "blogger_publish_enabled": self.config.blogger_enabled,
            "blogger_blog_id": _mask(self.config.blogger_blog_id),
            "blogger_access_token": _mask(self.config.blogger_access_token),
            "blogger_oauth_client_id": _mask(self.config.blogger_oauth_client_id),
            "adsense_enabled": self.config.adsense_enabled,
            "adsense_publisher_id": _mask(self.config.adsense_publisher_id),
            "schedule_interval_seconds": self.config.schedule_interval_seconds,
            "scheduler_configured": self.scheduler.interval_seconds > 0,
        }

    def blogger_authorization_url(self):
        if not self.config.blogger_oauth_client_id:
            return None
        query = urllib.parse.urlencode({
            "client_id": self.config.blogger_oauth_client_id,
            "redirect_uri": self.config.blogger_oauth_redirect_uri,
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/blogger",
            "state": self.oauth_state,
            "access_type": "offline",
            "prompt": "consent",
        })
        return "https://accounts.google.com/o/oauth2/v2/auth?" + query


class _Handler(BaseHTTPRequestHandler):
    service = None

    def _send(self, status, payload, content_type="application/json"):
        data = payload if isinstance(payload, bytes) else payload.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            self._send(200, _PAGE, "text/html; charset=utf-8")
        elif self.path == "/api/status":
            self._send(200, json.dumps(self.service.status()))
        elif self.path == "/oauth/blogger/start":
            url = self.service.blogger_authorization_url()
            if not url:
                self._send(503, json.dumps({"error": "Set BLOGGER_OAUTH_CLIENT_ID before linking Blogger"}))
            else:
                self.send_response(302)
                self.send_header("Location", url)
                self.end_headers()
        elif self.path.startswith("/oauth/blogger/callback"):
            self._send(501, "OAuth callback received. Exchange the code server-side and store the token in BLOGGER_ACCESS_TOKEN.", "text/plain")
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if self.path not in {"/api/preview", "/api/publish"}:
            self._send(404, json.dumps({"error": "not found"}))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 64 * 1024:
                raise ValueError("request is too large")
            payload = json.loads(self.rfile.read(length))
            if self.path == "/api/preview":
                request = ContentRequest(
                    topic=str(payload["topic"]), audience=str(payload.get("audience", "general readers")),
                    keywords=tuple(str(x) for x in payload.get("keywords", [])),
                )
                article = self.service.engine.preview(request)
                self._send(200, json.dumps({"article": article.__dict__, "dry_run": True}, default=str))
            else:
                if not self.service.config.blogger_enabled:
                    raise ContentEngineError("publishing is disabled; set BLOGGER_PUBLISH_ENABLED=true")
                from .models import Article
                article = self.service.engine.publish(Article(
                    title=str(payload["title"]), body=str(payload["body"]),
                    claims=tuple(str(x) for x in payload.get("claims", [])),
                ))
                self._send(200, json.dumps({"article": article.__dict__}, default=str))
        except (KeyError, TypeError, ValueError, ConfigError, ContentEngineError) as exc:
            self._send(400, json.dumps({"error": str(exc)}))

    def log_message(self, format, *args):
        return


def create_server(config: EngineConfig, engine=None, host="127.0.0.1", port=8765):
    config.validate()
    service = ControlService(config, engine or ContentEngine(config))
    handler = type("ContentEngineHandler", (_Handler,), {"service": service})
    return ThreadingHTTPServer((host, port), handler)
