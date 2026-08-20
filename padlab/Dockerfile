# 판독 실험 관리 서버 이미지.
#
# 판독은 하지 않는다. padservice 에 경로를 넘겨 부르는 쪽이라 OpenCV 가
# 필요 없고, 그래서 이미지가 판독 서비스보다 훨씬 가볍다.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 의존성만 먼저 굳힌다. 소스가 바뀌어도 이 레이어는 다시 받지 않는다.
COPY pyproject.toml ./
COPY server/__init__.py server/__init__.py
RUN pip install --no-cache-dir . && pip uninstall -y padlab

COPY server/ server/
COPY migrations/ migrations/
COPY web/ web/

# 루트로 돌리지 않는다. 업로드 파일을 받아 볼륨에 쓰는 서비스라 더 그렇다.
# 공유 볼륨에 쓸 수 있어야 하므로 UID 를 고정해 둔다.
# 공유 볼륨을 쓸 수 있게 소유권을 미리 잡아 둔다. 도커가 빈 이름 볼륨을
# 처음 붙일 때 이미지 쪽 디렉터리의 소유권을 그대로 가져가므로, 여기서
# 잡아 두지 않으면 root 소유가 되어 이 사용자가 쓸 수 없다.
RUN useradd --create-home --uid 10002 padlab     && mkdir -p /data     && chown -R padlab:padlab /app /data
USER padlab

EXPOSE 8912

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8912/healthz', timeout=4)"

CMD ["python", "-m", "server", "--host", "0.0.0.0", "--port", "8912"]
