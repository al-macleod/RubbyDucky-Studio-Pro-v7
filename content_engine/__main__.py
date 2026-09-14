"""Launch the localhost control UI with ``python -m content_engine``."""

import argparse
import os

from .config import EngineConfig
from .control import create_server
from .pipeline import ContentEngine
from .platform import create_platform_server


def main():
    parser = argparse.ArgumentParser(description="Run the local content engine control UI")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (localhost by default)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--platform", action="store_true", help="Run the first-party blog platform instead of the control UI")
    parser.add_argument("--db", default=os.environ.get("BLOG_DB_PATH", "macleod_method.db"))
    args = parser.parse_args()
    config = EngineConfig.from_env()
    if args.platform:
        server = create_platform_server(
            ContentEngine(config),
            db_path=args.db,
            admin_token=os.environ.get("CONTENT_ADMIN_TOKEN", ""),
            host=args.host,
            port=args.port,
        )
    else:
        server = create_server(config, host=args.host, port=args.port)
    print(f"Content Engine UI: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
