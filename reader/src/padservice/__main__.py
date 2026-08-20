"""서비스 기동.

    python -m padservice

호스트·포트는 설정에서 읽고, 명령행 인자가 있으면 그쪽이 이긴다.
워커 수는 ``PADREADER_WORKERS`` 환경변수로도 줄 수 있다 — 컨테이너에서
이미지를 다시 굽지 않고 조절하기 위해서다.

기동 전에 설정 파일을 한 번 읽어 본다. 경로가 어긋났으면 여기서 죽는 편이
낫다. 임계값이 적용되지 않은 채 서비스가 정상처럼 뜨는 것이 가장 나쁜
결과이기 때문이다.
"""

from __future__ import annotations

import argparse
import os
import sys

import uvicorn

from padreader.config import load_config, resolve_config_path

WORKERS_ENV_VAR = "PADREADER_WORKERS"


def main(argv: list[str] | None = None) -> int:
    # 인자를 먼저 읽는다. 호스트·포트 기본값이 설정에서 오지만, 그렇다고
    # 설정 로드를 앞에 두면 --help 조차 설정 파일에 걸려 죽는다.
    parser = argparse.ArgumentParser(description="참조 패드 판독 서비스")
    parser.add_argument("--host", default=None, help="기본값은 설정의 service.host")
    parser.add_argument("--port", type=int, default=None, help="기본값은 설정의 service.port")
    parser.add_argument(
        "--workers", type=int, default=int(os.environ.get(WORKERS_ENV_VAR, "1"))
    )
    parser.add_argument("--reload", action="store_true", help="개발용. 워커 수를 무시한다")
    args = parser.parse_args(argv)

    try:
        config = load_config()
    except FileNotFoundError as exc:
        print(f"설정을 읽을 수 없다: {exc}", file=sys.stderr)
        return 1

    host = args.host if args.host is not None else config.service.host
    port = args.port if args.port is not None else config.service.port

    source = resolve_config_path()
    print(f"설정: {source or '(파일 없음, 기본값 사용)'}", file=sys.stderr)
    print(
        f"규격: {config.spec} | 분진 임계: {config.dust.depth_threshold}",
        file=sys.stderr,
    )

    uvicorn.run(
        "padservice.app:app",
        host=host,
        port=port,
        workers=None if args.reload else max(1, args.workers),
        reload=args.reload,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
