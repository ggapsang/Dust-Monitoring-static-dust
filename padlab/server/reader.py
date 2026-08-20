"""판독 서비스 클라이언트.

``padservice`` 는 손대지 않는다. 여기서는 ``POST /read/path`` 로 경로만
넘기고 응답을 그대로 받는다.

**결과 이미지는 판독 직후 곧바로 내려받는다.** 서비스가 이미지를 30분,
64건까지만 들고 있어서 - 사진 서른 장에 패드가 두세 개씩이면 일괄 판독을
다 돌린 뒤에는 앞쪽이 이미 밀려나 있다.

실패 사유의 한글 표기를 여기서 다시 만들지 않는다. 응답의 ``summary`` 에
이미 들어 있고, 같은 문구를 양쪽에 두면 조용히 어긋난다. 화면 표시는
``summary``, 필터·집계는 원문 ``failure_reason`` 을 쓴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


class ReaderError(RuntimeError):
    """판독 서비스가 요청을 받아들이지 않았다. 사진 한 장의 실패로 다룬다."""


@dataclass
class ReadOutcome:
    payload: dict[str, Any]
    images: list[dict[str, bytes]]
    """패드 순서와 같은 목록. 내려받지 못한 종류는 빠져 있다."""


class ReaderClient:
    def __init__(self, base_url: str, timeout_sec: float) -> None:
        self._base = base_url.rstrip("/")
        self._timeout = timeout_sec

    async def healthz(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self._base}/healthz")
            response.raise_for_status()
            return response.json()

    async def config(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{self._base}/config")
            response.raise_for_status()
            return response.json()

    async def read_path(
        self,
        path: str,
        baseline_paths: list[str],
        tone: str,
        overrides: dict[str, Any] | None = None,
        expected_ids: list[str] | None = None,
    ) -> ReadOutcome:
        body = {
            "path": path,
            "baseline_path": baseline_paths,
            "tone": tone,
            "visualize": True,
            "config": overrides or None,
            # 이 사진에 있을 개소를 함께 보낸다. 숫자를 자유롭게 읽는 대신
            # 후보 안에서 배정하게 하면 없는 번호가 나오지 않는다.
            "expected_point_ids": expected_ids or None,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(f"{self._base}/read/path", json=body)
            if response.status_code >= 400:
                raise ReaderError(_message(response))
            payload = response.json()

            images = []
            for pad in payload.get("pads") or []:
                images.append(await self._fetch_images(client, pad.get("images")))
        return ReadOutcome(payload=payload, images=images)

    async def _fetch_images(
        self, client: httpx.AsyncClient, links: dict[str, str] | None
    ) -> dict[str, bytes]:
        """이미지를 내려받는다. 한 장을 못 받아도 나머지는 저장한다."""
        if not links:
            return {}
        frames: dict[str, bytes] = {}
        for kind, url in links.items():
            try:
                got = await client.get(url)
            except httpx.HTTPError:
                continue
            if got.status_code == 200:
                frames[kind] = got.content
        return frames


def _message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}: {response.text[:200]}"
    detail = body.get("detail") if isinstance(body, dict) else None
    return f"HTTP {response.status_code}: {detail or str(body)[:200]}"
