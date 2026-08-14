# 참조 패드 판독 서비스 이미지.
#
# 설정 파일은 이미지에 굽지 않고 마운트해 쓴다. 임계값이 실증에서 반복
# 조정되는데 그때마다 이미지를 다시 굽는 것은 말이 안 되기 때문이다.
# PADREADER_CONFIG 가 가리키는 파일이 없으면 기동 시점에 실패한다 —
# 임계값이 적용되지 않은 채 정상처럼 도는 것보다 낫다.

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 의존성만 먼저 굳힌다. 소스가 바뀌어도 이 레이어는 다시 받지 않는다.
#
# opencv 를 headless 로 바꿔 끼운다. 판독기는 imshow 같은 GUI 를 전혀 쓰지
# 않는데, 일반 opencv-python 은 import 만으로 libGL 을 요구해서 apt 로
# 216MB 를 더 깔아야 한다. pyproject 에는 일반 패키지를 두었다 — 거기서
# headless 를 선언하면 개발 장비에 두 배포판이 겹쳐 설치되어 cv2 파일이
# 서로 덮어쓴다. 그래서 교체는 컨테이너 안에서만 한다.
COPY pyproject.toml ./
COPY src/padreader/__init__.py src/padreader/__init__.py
RUN pip install --no-cache-dir ".[service]" \
    && pip uninstall -y padreader opencv-python \
    && pip install --no-cache-dir opencv-python-headless

COPY src/ src/
COPY config/ config/
RUN pip install --no-cache-dir --no-deps .

# 루트로 돌리지 않는다. 업로드 이미지를 디코드하는 서비스라 더 그렇다.
RUN useradd --create-home --uid 10001 padreader \
    && chown -R padreader:padreader /app
USER padreader

ENV PADREADER_CONFIG=/app/config/default.yaml
EXPOSE 8911

# curl 이 없는 슬림 이미지라 파이썬으로 확인한다.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8911/healthz', timeout=4)"

# 워커 수는 환경변수로 조절한다. 장당 400~500ms 라 한 프로세스의 처리량이
# 초당 두 장 남짓이고, OpenCV 가 GIL 을 놓지 않는 구간이 있어 스레드만으로는
# 코어를 다 쓰지 못한다.
ENV PADREADER_WORKERS=1
CMD ["python", "-m", "padservice", "--host", "0.0.0.0", "--port", "8911"]
