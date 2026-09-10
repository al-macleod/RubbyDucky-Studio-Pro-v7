# RubbyDucky-Studio-Pro-v7
A No-Code highly customizable BadUSB Payload editor/generator.

## Autonomous content engine

The isolated Python `content_engine` package provides safe, provider-agnostic
article generation. It validates configuration, retries transient provider
failures, emits structured JSON log events, and checks for unsafe cyber
guidance, fabricated claims, and promotional spam.

Publishing is disabled by default. Configure credentials through environment
variables; never commit them:

```powershell
$env:CONTENT_PROVIDER_URL = "https://your-provider.example/v1/chat/completions"
$env:CONTENT_PROVIDER_API_KEY = "<secret>"
$env:BLOGGER_PUBLISH_ENABLED = "false"
python -c "from content_engine.config import EngineConfig; print(EngineConfig.from_env())"
```

Set `BLOGGER_PUBLISH_ENABLED=true` only with `BLOGGER_BLOG_ID` and
`BLOGGER_ACCESS_TOKEN`. For account linking, also provide
`BLOGGER_OAUTH_CLIENT_ID`; the local callback is restricted to localhost and
does not store tokens. The package does not contain a daemon or automatically
publish content: callers can use `IntervalScheduler` to trigger a reviewed
`ContentEngine.preview` followed by explicit `ContentEngine.publish`.

Start the local control UI after exporting the provider settings:

```powershell
python -m content_engine
```

Use `--host 127.0.0.1` (the default) for local operation. Do not expose this
control server directly to the public internet; place it behind authenticated
network access if it must be reached remotely.

The UI provides masked health/configuration status, Blogger account-link
redirect setup, AdSense configuration visibility, preview/dry-run generation,
and a separate publish action. AdSense identifiers are configuration only;
the engine does not claim approval, traffic, or revenue.

### Prerequisites for continuous 30-minute publication

This checkpoint intentionally does not claim a live blog or AdSense account.
To prove continuous publication in a deployment, an operator still needs:

1. A reachable provider endpoint and secret `CONTENT_PROVIDER_API_KEY`.
2. A Google Cloud OAuth client configured for the exact localhost callback
   during setup, followed by a real Blogger blog ID and OAuth access/refresh
   token stored in a secret manager.
3. A process supervisor (systemd, Windows Task Scheduler, or a container
   scheduler) that invokes the preview/review/publish workflow every 1800
   seconds and restarts on failure.
4. A real Blogger test post and rollback/duplicate-prevention policy before
   enabling `BLOGGER_PUBLISH_ENABLED=true`.
5. An approved AdSense account and site review, plus verified publisher/slot
   identifiers; configuration alone cannot establish eligibility or revenue.

Run focused tests with:

```powershell
python -m unittest discover -s tests -v
```
