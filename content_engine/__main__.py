"""Launch the localhost control UI with ``python -m content_engine``."""

import argparse

from .config import EngineConfig
from .control import create_server


def main():
    parser = argparse.ArgumentParser(description="Run the local content engine control UI")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (localhost by default)")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    config = EngineConfig.from_env()
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
