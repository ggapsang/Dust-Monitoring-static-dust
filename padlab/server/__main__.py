"""기동 진입점.

    python -m server --host 0.0.0.0 --port 8912
"""

from __future__ import annotations

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="판독 실험 관리 서버")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8912)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()
    uvicorn.run("server.app:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
