"""First-party SQLite blog and local admin surface for Macleod's Method."""

import html
import json
import re
import secrets
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from .models import Article, ContentRequest
from .pipeline import ContentEngine


class _ManagedConnection(sqlite3.Connection):
    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _slugify(title):
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:80] or "untitled"


class BlogStore:
    """Small SQLite persistence layer with no external database dependency."""

    def __init__(self, path="macleod_method.db"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self):
        connection = sqlite3.connect(self.path, factory=_ManagedConnection)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self):
        with self._connect() as db:
            db.execute(
                """CREATE TABLE IF NOT EXISTS posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    claims TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL CHECK(status IN ('draft', 'published')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    published_at TEXT
                )"""
            )
            db.execute("CREATE INDEX IF NOT EXISTS idx_posts_status_published ON posts(status, published_at DESC)")

    def create_draft(self, article: Article):
        now = _utc_now()
        slug = _slugify(article.title)
        with self._connect() as db:
            existing = db.execute("SELECT id FROM posts WHERE slug = ?", (slug,)).fetchone()
            if existing:
                slug = f"{slug}-{secrets.token_hex(3)}"
            cursor = db.execute(
                """INSERT INTO posts
                (slug, title, body, claims, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'draft', ?, ?)""",
                (slug, article.title, article.body, json.dumps(article.claims), now, now),
            )
            post_id = cursor.lastrowid
        return self.get(post_id)

    def get(self, post_id):
        with self._connect() as db:
            row = db.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
        return dict(row) if row else None

    def get_by_slug(self, slug, published_only=True):
        query = "SELECT * FROM posts WHERE slug = ?"
        params = [slug]
        if published_only:
            query += " AND status = 'published'"
        with self._connect() as db:
            row = db.execute(query, params).fetchone()
        return dict(row) if row else None

    def list_posts(self, published_only=False):
        query = "SELECT * FROM posts"
        if published_only:
            query += " WHERE status = 'published'"
        query += " ORDER BY COALESCE(published_at, created_at) DESC"
        with self._connect() as db:
            return [dict(row) for row in db.execute(query)]

    def publish(self, post_id):
        now = _utc_now()
        with self._connect() as db:
            db.execute(
                "UPDATE posts SET status = 'published', published_at = COALESCE(published_at, ?), updated_at = ? WHERE id = ?",
                (now, now, post_id),
            )
        return self.get(post_id)


def _article_from_row(row):
    return Article(
        title=row["title"],
        body=row["body"],
        claims=tuple(json.loads(row["claims"])),
        generated_at=datetime.fromisoformat(row["created_at"]),
    )


class BlogService:
    def __init__(self, engine: ContentEngine, store: BlogStore):
        self.engine = engine
        self.store = store

    def generate_draft(self, request):
        article = self.engine.preview(request)
        return self.store.create_draft(article)

    def publish(self, post_id):
        row = self.store.get(post_id)
        if not row:
            raise ValueError("post not found")
        if row["status"] == "published":
            return row
        self.engine.validate_for_publication(_article_from_row(row))
        return self.store.publish(post_id)


_PUBLIC_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Macleod's Method</title><style>
body{{font:17px Georgia,serif;max-width:850px;margin:3rem auto;padding:0 1rem;color:#222}}
a{{color:#164e63}}article{{border-bottom:1px solid #ddd;padding:1.5rem 0}}
.meta{{color:#666;font:14px system-ui}}h1,h2{{font-family:system-ui,sans-serif}}
</style></head><body><h1>Macleod's Method</h1>
<p>Real stories. Real protection. Practical lessons from the edge of the system.</p>
{content}</body></html>"""


_ADMIN_PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Macleod's Method Admin</title><style>
body{font:16px system-ui;max-width:900px;margin:2rem auto;padding:0 1rem}
label{display:block;margin:.7rem 0}input,textarea{width:100%;box-sizing:border-box;padding:.5rem}
button{padding:.55rem;margin:.3rem 0}.draft{border:1px solid #ddd;padding:1rem;margin:1rem 0}
pre{white-space:pre-wrap;background:#f6f6f6;padding:1rem}</style></head><body>
<h1>Macleod's Method Admin</h1>
<p>Local admin surface. The token stays in this browser tab and is never sent anywhere except this host.</p>
<label>Admin token<input id="token" type="password" autocomplete="off"></label>
<form id="generate"><label>Topic<input id="topic" required maxlength="240"></label>
<label>Audience<input id="audience" value="general readers"></label>
<label>Keywords<input id="keywords" placeholder="comma,separated"></label>
<button>Generate draft</button></form><pre id="message"></pre><div id="posts"></div>
<script>
const token=document.getElementById('token'), message=document.getElementById('message');
token.value=sessionStorage.getItem('macleod-admin-token')||'';
token.onchange=()=>sessionStorage.setItem('macleod-admin-token',token.value);
function headers(){return {'Authorization':'Bearer '+token.value,'Content-Type':'application/json'}}
async function load(){const r=await fetch('/api/admin/posts',{headers:headers()});
if(!r.ok){message.textContent='Authorization required';return} const posts=await r.json();
document.getElementById('posts').innerHTML=posts.map(p=>`<div class="draft"><b>${p.title}</b>
<p>${p.status} - ${p.slug}</p>${p.status==='draft'?`<button onclick="publish(${p.id})">Publish reviewed draft</button>`:''}</div>`).join('')}
async function publish(id){const r=await fetch('/api/admin/posts/'+id+'/publish',{method:'POST',headers:headers()});
message.textContent=JSON.stringify(await r.json(),null,2);load()}
document.getElementById('generate').onsubmit=async(e)=>{e.preventDefault();const r=await fetch('/api/admin/generate',
{method:'POST',headers:headers(),body:JSON.stringify({topic:topic.value,audience:audience.value,
keywords:keywords.value.split(',').map(x=>x.trim()).filter(Boolean)})});message.textContent=JSON.stringify(await r.json(),null,2);load()}
load();
</script></body></html>"""


def _render_post(row):
    return "<article><h2><a href='/post/{0}'>{1}</a></h2><div class='meta'>{2}</div><p>{3}</p></article>".format(
        html.escape(row["slug"]), html.escape(row["title"]), html.escape(row["published_at"] or ""),
        html.escape(row["body"][:320]) + ("..." if len(row["body"]) > 320 else ""),
    )


class _PlatformHandler(BaseHTTPRequestHandler):
    service = None
    admin_token = ""

    def _send(self, status, payload, content_type="application/json"):
        data = payload if isinstance(payload, bytes) else payload.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self):
        supplied = self.headers.get("Authorization", "")
        return bool(self.admin_token) and secrets.compare_digest(supplied, f"Bearer {self.admin_token}")

    def do_GET(self):
        if self.path == "/":
            posts = self.service.store.list_posts(published_only=True)
            content = "".join(_render_post(post) for post in posts) or "<p>No published stories yet.</p>"
            self._send(200, _PUBLIC_PAGE.format(content=content), "text/html; charset=utf-8")
        elif self.path == "/admin":
            self._send(200, _ADMIN_PAGE, "text/html; charset=utf-8")
        elif self.path.startswith("/post/"):
            row = self.service.store.get_by_slug(unquote(self.path[6:]))
            if not row:
                self._send(404, "Not found", "text/plain")
            else:
                body = "<article><h1>{}</h1><div class='meta'>{}</div><p>{}</p></article>".format(
                    html.escape(row["title"]), html.escape(row["published_at"] or ""), html.escape(row["body"]).replace("\n", "<br>")
                )
                self._send(200, _PUBLIC_PAGE.format(content=body), "text/html; charset=utf-8")
        elif self.path == "/api/admin/posts":
            if not self._authorized():
                self._send(401, json.dumps({"error": "admin authorization required"}))
            else:
                self._send(200, json.dumps(self.service.store.list_posts()))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        if not self._authorized():
            self._send(401, json.dumps({"error": "admin authorization required"}))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 64 * 1024:
                raise ValueError("request is too large")
            payload = json.loads(self.rfile.read(length))
            if self.path == "/api/admin/generate":
                row = self.service.generate_draft(ContentRequest(
                    topic=str(payload["topic"]), audience=str(payload.get("audience", "general readers")),
                    keywords=tuple(str(value) for value in payload.get("keywords", [])),
                ))
                self._send(201, json.dumps(row))
            elif self.path.startswith("/api/admin/posts/") and self.path.endswith("/publish"):
                post_id = int(self.path.split("/")[4])
                self._send(200, json.dumps(self.service.publish(post_id)))
            else:
                self._send(404, json.dumps({"error": "not found"}))
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self._send(400, json.dumps({"error": str(exc)}))

    def log_message(self, format, *args):
        return


class _PlatformServer(ThreadingHTTPServer):
    daemon_threads = True


def create_platform_server(engine, db_path="macleod_method.db", admin_token="", host="127.0.0.1", port=8787):
    """Create the first-party blog server; bind publicly only behind a proxy."""
    if not admin_token:
        raise ValueError("admin_token is required; set an unguessable secret")
    service = BlogService(engine, BlogStore(db_path))
    handler = type("MacleodMethodHandler", (_PlatformHandler,), {"service": service, "admin_token": admin_token})
    return _PlatformServer((host, port), handler)
