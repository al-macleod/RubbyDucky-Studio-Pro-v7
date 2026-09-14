import unittest
import json
import threading
import urllib.request
import subprocess
import sys
import tempfile

from content_engine.config import ConfigError, EngineConfig
from content_engine.control import ControlService, create_server
from content_engine.models import Article, ContentRequest
from content_engine.pipeline import ContentEngine, ContentEngineError
from content_engine.platform import BlogService, BlogStore, create_platform_server
from content_engine.providers import ProviderError
from content_engine.scheduler import IntervalScheduler
from content_engine.safety import SafetyError


class FakeProvider:
    name = "fake"

    def generate(self, request):
        return Article("A useful guide", "Evidence-aware content.", claims=("A claim",))


class FlakyProvider:
    name = "flaky"

    def __init__(self):
        self.calls = 0

    def generate(self, request):
        self.calls += 1
        if self.calls == 1:
            raise ProviderError("temporary failure")
        return Article("Recovered guide", "Evidence-aware content.", claims=("A claim",))


def config(**overrides):
    values = {"provider": "fake", "provider_url": "https://provider.example.test/generate", "provider_api_key": "test-only"}
    values.update(overrides)
    return EngineConfig(**values)


class ContentEngineTests(unittest.TestCase):
    def test_generation_does_not_publish_by_default(self):
        article = ContentEngine(config(), provider=FakeProvider()).run(ContentRequest("How to evaluate sources"))
        self.assertEqual(article.title, "A useful guide")
        self.assertIsNone(article.blogger_url)

    def test_unsafe_topic_is_rejected_before_provider(self):
        with self.assertRaises(SafetyError):
            ContentEngine(config(), provider=FakeProvider()).run(ContentRequest("how to steal passwords"))

    def test_blogger_requires_credentials_when_enabled(self):
        with self.assertRaises(ConfigError):
            config(blogger_enabled=True).validate()

    def test_env_config_defaults_publishing_off(self):
        result = EngineConfig.from_env({"CONTENT_PROVIDER_URL": "https://provider.example.test", "CONTENT_PROVIDER_API_KEY": "test-only"})
        self.assertFalse(result.blogger_enabled)

    def test_provider_retries_transient_failure(self):
        provider = FlakyProvider()
        article = ContentEngine(config(max_retries=1), provider=provider).run(ContentRequest("A safe topic"))
        self.assertEqual(article.title, "Recovered guide")
        self.assertEqual(provider.calls, 2)

    def test_scheduler_only_runs_when_due(self):
        now = [10.0]
        scheduler = IntervalScheduler(5, clock=lambda: now[0])
        self.assertTrue(scheduler.due())
        self.assertFalse(scheduler.due())
        now[0] = 15.0
        self.assertTrue(scheduler.due())

    def test_exhausted_provider_retries_are_explicit(self):
        class BrokenProvider:
            name = "broken"
            def generate(self, request):
                raise ProviderError("permanent failure")

        with self.assertRaises(ContentEngineError):
            ContentEngine(config(max_retries=0), provider=BrokenProvider()).run(ContentRequest("A safe topic"))

    def test_preview_is_dry_run_and_status_masks_secrets(self):
        service = ControlService(config(provider_api_key="super-secret"), ContentEngine(config(), provider=FakeProvider()))
        article = service.engine.preview(ContentRequest("A safe topic"))
        status = service.status()
        self.assertIsNone(article.blogger_url)
        self.assertEqual(status["provider_api_key"], "configured")
        self.assertNotIn("super-secret", str(status))

    def test_blogger_oauth_url_requires_client_id_and_uses_state(self):
        service = ControlService(config(), ContentEngine(config(), provider=FakeProvider()))
        self.assertIsNone(service.blogger_authorization_url())
        linked = ControlService(
            config(blogger_oauth_client_id="client-id"),
            ContentEngine(config(blogger_oauth_client_id="client-id"), provider=FakeProvider()),
        )
        url = linked.blogger_authorization_url()
        self.assertIn("accounts.google.com", url)
        self.assertIn("state=" + linked.oauth_state, url)

    def test_local_control_server_serves_masked_status_and_preview(self):
        server = create_server(config(provider_api_key="server-secret"), ContentEngine(config(), provider=FakeProvider()), port=0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:%d" % server.server_address[1]
        try:
            status = json.loads(urllib.request.urlopen(base + "/api/status").read())
            self.assertEqual(status["provider_api_key"], "configured")
            request = urllib.request.Request(
                base + "/api/preview",
                data=json.dumps({"topic": "A safe topic"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            preview = json.loads(urllib.request.urlopen(request).read())
            self.assertTrue(preview["dry_run"])
            self.assertEqual(preview["article"]["title"], "A useful guide")
        finally:
            server.shutdown()
            server.server_close()

    def test_module_launcher_help_is_available(self):
        result = subprocess.run(
            [sys.executable, "-m", "content_engine", "--help"],
            capture_output=True, text=True, check=True,
        )
        self.assertIn("Run the local content engine control UI", result.stdout)

    def test_first_party_store_keeps_drafts_private_until_published(self):
        with tempfile.TemporaryDirectory() as directory:
            store = BlogStore(directory + "/blog.db")
            service = BlogService(ContentEngine(config(), provider=FakeProvider()), store)
            draft = service.generate_draft(ContentRequest("A safe topic"))
            self.assertEqual(draft["status"], "draft")
            self.assertEqual(store.list_posts(published_only=True), [])
            published = service.publish(draft["id"])
            self.assertEqual(published["status"], "published")
            self.assertEqual(store.get_by_slug(draft["slug"])["id"], draft["id"])

    def test_first_party_server_requires_admin_token_and_serves_published_post(self):
        with tempfile.TemporaryDirectory() as directory:
            store = BlogStore(directory + "/blog.db")
            service = BlogService(ContentEngine(config(), provider=FakeProvider()), store)
            draft = service.generate_draft(ContentRequest("A safe topic"))
            service.publish(draft["id"])
            server = create_platform_server(
                service.engine, directory + "/blog.db", admin_token="test-admin", port=0
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = "http://127.0.0.1:%d" % server.server_address[1]
            try:
                public = urllib.request.urlopen(base + "/").read().decode()
                self.assertIn("A useful guide", public)
                admin = urllib.request.urlopen(base + "/admin").read().decode()
                self.assertIn("Macleod's Method Admin", admin)
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    urllib.request.urlopen(base + "/api/admin/posts")
                self.assertEqual(denied.exception.code, 401)
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
