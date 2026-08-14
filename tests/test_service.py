"""판독 서비스 검증.

서비스가 코어를 제대로 감쌌는지, 감싸면서 상태를 들이지 않았는지, 그리고
**응답을 눈으로 읽을 수 있는지**를 본다. 판독 정확도 자체는
``test_pipeline.py`` 가 다룬다.
"""

from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

from padreader import spec
from padtools.synth import CaptureParams, synthesize, vary

fastapi_testclient = pytest.importorskip("fastapi.testclient")

from padservice.app import MAX_BATCH, app  # noqa: E402

SPEC_NAME = "v2_protected"
SPEC = spec.SPECS[SPEC_NAME]
BASE = CaptureParams(pad_fill=0.55, black_level=10, gain=0.95, noise_sigma=0.8, seed=5)


@pytest.fixture(scope="module")
def client():
    with fastapi_testclient.TestClient(app) as test_client:
        yield test_client


def encoded(tone: str, params: CaptureParams = BASE, target_id: str = "1078") -> bytes:
    image, _ = synthesize(SPEC, tone, params, target_id=target_id)
    ok, buffer = cv2.imencode(".png", image)
    assert ok
    return buffer.tobytes()


def post_read(client, tone: str, params: CaptureParams = BASE, **kwargs):
    """이미지 한 장 업로드."""
    return post_many(client, [("pad.png", encoded(tone, params))], tone, **kwargs)


def post_many(client, blobs: list[tuple[str, bytes]], tone: str = "white", **kwargs):
    overrides = kwargs.pop("overrides", {})
    overrides.setdefault("spec", SPEC_NAME)
    return client.post(
        "/read",
        params={"tone": tone, **kwargs},
        files=[("files", (name, blob, "image/png")) for name, blob in blobs],
        data={"config": json.dumps(overrides)},
    )


def only(response) -> dict:
    """한 장짜리 응답에서 그 한 장의 결과를 꺼낸다."""
    body = response.json()
    assert body["count"] == 1, body
    return body["results"][0]


# ---------------------------------------------------------------------------
# 기본
# ---------------------------------------------------------------------------


def test_healthz(client) -> None:
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert SPEC_NAME in response.json()["specs"]


def test_config_exposes_values_and_source(client) -> None:
    body = client.get("/config").json()
    values = body["values"]
    assert values["service"]["port"] == 8911
    assert "max_tilt_deg" in values["quality"]
    assert body["source"] is None or body["source"].endswith(".yaml")


@pytest.mark.parametrize("tone", ("white", "black"))
def test_read_returns_score(client, tone: str) -> None:
    result = only(post_read(client, tone, vary(BASE, dust_coverage=0.2)))
    assert result["success"], result
    assert result["dust_score"] == pytest.approx(0.2, abs=0.05)
    assert result["pad_tone"] == tone
    assert result["spec_name"] == SPEC_NAME
    assert result["target_id"] == "1078"
    assert result["file"] == "pad.png"


# ---------------------------------------------------------------------------
# 여러 장 한 번에
# ---------------------------------------------------------------------------


def test_reads_many_images_in_one_request(client) -> None:
    blobs = [
        (f"cov{int(c * 100):02d}.png", encoded("white", vary(BASE, dust_coverage=c)))
        for c in (0.0, 0.2, 0.5)
    ]
    body = post_many(client, blobs).json()

    assert body["count"] == 3
    assert body["succeeded"] == 3
    assert [r["file"] for r in body["results"]] == [name for name, _ in blobs]

    # 도포량이 늘수록 스코어도 커져야 한다.
    scores = [r["dust_score"] for r in body["results"]]
    assert scores == sorted(scores), scores


def test_batch_summary_covers_the_whole_request(client) -> None:
    blobs = [
        (f"cov{int(c * 100):02d}.png", encoded("white", vary(BASE, dust_coverage=c)))
        for c in (0.0, 0.5)
    ]
    summary = post_many(client, blobs).json()["summary"]
    assert "2장 모두 판독 성공" in summary
    assert "~" in summary, "스코어 범위가 보여야 한다"
    assert "초" in summary


def test_single_image_summary_is_not_padded_with_counts(client) -> None:
    """한 장이면 '1장 중 1장' 같은 군더더기 없이 그 한 장의 요약을 쓴다."""
    body = post_read(client, "white", vary(BASE, dust_coverage=0.2)).json()
    assert body["summary"] == body["results"][0]["summary"]
    assert body["summary"].startswith("판독 성공")


def test_one_broken_image_does_not_sink_the_rest(client) -> None:
    """한 장이 깨져도 나머지는 그대로 판독해야 한다."""
    blobs = [
        ("good.png", encoded("white", vary(BASE, dust_coverage=0.2))),
        ("junk.png", b"not an image"),
        ("good2.png", encoded("white", vary(BASE, dust_coverage=0.5))),
    ]
    body = post_many(client, blobs).json()

    assert body["count"] == 3
    assert body["succeeded"] == 2
    assert body["results"][1]["success"] is False
    assert body["results"][1]["failure_reason"] == "invalid_image"
    assert body["results"][0]["dust_score"] is not None
    assert body["results"][2]["dust_score"] is not None
    assert "2장 성공" in body["summary"] and "1장 판독 불가" in body["summary"]


def test_batch_size_is_capped(client) -> None:
    blob = encoded("white")
    blobs = [(f"{i}.png", blob) for i in range(MAX_BATCH + 1)]
    response = post_many(client, blobs)
    assert response.status_code == 400
    assert str(MAX_BATCH) in response.json()["detail"]


# ---------------------------------------------------------------------------
# 응답을 눈으로 읽을 수 있는가
# ---------------------------------------------------------------------------


def test_default_response_is_compact(client) -> None:
    """기본 응답에 무거운 것이 딸려오지 않아야 한다."""
    result = only(post_read(client, "white", vary(BASE, dust_coverage=0.2)))
    for heavy in ("cells", "quality", "normalization", "line_contrasts", "corners"):
        assert result[heavy] is None, heavy

    for key in ("success", "summary", "dust_score", "dispersion", "target_id", "elapsed_ms"):
        assert result[key] is not None, key


def test_summary_reads_like_a_sentence(client) -> None:
    summary = only(post_read(client, "white", vary(BASE, dust_coverage=0.2)))["summary"]
    assert "판독 성공" in summary
    assert "분진 0.19" in summary or "분진 0.20" in summary
    assert "ID 1078" in summary
    assert "ms" in summary


def test_summary_explains_failure(client) -> None:
    blank = np.full((400, 600, 3), 120, np.uint8)
    ok, buffer = cv2.imencode(".png", blank)
    assert ok

    result = only(post_many(client, [("blank.png", buffer.tobytes())]))
    assert result["success"] is False
    assert result["summary"].startswith("판독 불가")
    assert "패드를 찾지 못함" in result["summary"]
    assert result["failure_reason"] == "pad_not_found"


def test_detail_flag_adds_diagnostics(client) -> None:
    result = only(post_read(client, "white", detail=True))
    assert result["quality"]["tilt_deg"] is not None
    assert result["normalization"]["method"] == "two_point"
    assert len(result["line_contrasts"]) == len(SPEC.line_bars)
    assert len(result["corners"]) == 4
    assert result["rotation_margin"] is not None
    assert result["cells"] is None, "detail 은 구획까지 켜지 않는다"


def test_include_cells_flag_adds_cells(client) -> None:
    result = only(post_read(client, "white", include_cells=True))
    assert len(result["cells"]) == 8 * 11
    assert result["quality"] is None, "구획 요청이 진단값까지 켜지 않는다"


def test_response_stays_small_by_default(client) -> None:
    body = post_read(client, "white", vary(BASE, dust_coverage=0.2)).json()
    assert len(json.dumps(body)) < 1500, "기본 응답이 여전히 무겁다"


def test_no_image_cache_endpoints(client) -> None:
    """토큰으로 이미지를 꺼내 가는 경로는 없어야 한다.

    이미지를 서버에 보관하지 않는다는 뜻이다. 필요할 때 바로 만들어 준다.
    """
    paths = client.get("/openapi.json").json()["paths"]
    assert not [p for p in paths if p.startswith("/images")], paths


# ---------------------------------------------------------------------------
# 판독 결과 이미지
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ("overlay", "rectified"))
def test_read_image_returns_png(client, kind: str) -> None:
    """무엇을 어디서 쟀는지 눈으로 볼 수 있어야 한다."""
    response = client.post(
        "/read/image",
        params={"tone": "white", "kind": kind},
        files={"file": ("pad.png", encoded("white", vary(BASE, dust_coverage=0.2)), "image/png")},
        data={"config": json.dumps({"spec": SPEC_NAME})},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"

    image = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
    assert image is not None
    assert image.shape[0] == image.shape[1] == 1120


def test_read_image_rejects_unknown_kind(client) -> None:
    response = client.post(
        "/read/image",
        params={"tone": "white", "kind": "nope"},
        files={"file": ("pad.png", encoded("white"), "image/png")},
    )
    assert response.status_code == 400


def test_read_image_explains_when_unreadable(client) -> None:
    """판독을 못 하면 빈 이미지를 주는 대신 이유를 말한다."""
    blank = np.full((400, 600, 3), 120, np.uint8)
    ok, buffer = cv2.imencode(".png", blank)
    assert ok

    response = client.post(
        "/read/image",
        params={"tone": "white"},
        files={"file": ("blank.png", buffer.tobytes(), "image/png")},
    )
    assert response.status_code == 422
    assert "패드를 찾지 못함" in response.json()["detail"]


# ---------------------------------------------------------------------------
# 설정 오버라이드
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_blank_config_means_no_override(client, blank: str) -> None:
    """빈 config 는 오류가 아니라 '오버라이드 없음' 이다."""
    response = client.post(
        "/read",
        params={"tone": "white"},
        files=[("files", ("pad.png", encoded("white"), "image/png"))],
        data={"config": blank},
    )
    assert response.status_code == 200
    assert only(response)["spec_name"] == "v2"


def test_config_form_field_defaults_to_blank(client) -> None:
    """문서 UI 가 config 를 안 채워도 요청이 성립해야 한다.

    폼 필드에 기본값이 없으면 문서 UI 가 스키마 예시인 "string" 을 그대로
    보내 JSON 파싱에서 튕긴다.
    """
    schema = client.get("/openapi.json").json()
    body = schema["paths"]["/read"]["post"]["requestBody"]["content"]
    form = next(iter(body.values()))["schema"]
    if "$ref" in form:
        form = schema["components"]["schemas"][form["$ref"].rsplit("/", 1)[-1]]
    assert form["properties"]["config"]["default"] == ""
    assert "config" not in form.get("required", [])


def test_literal_placeholder_config_reports_what_it_got(client) -> None:
    response = client.post(
        "/read",
        params={"tone": "white"},
        files=[("files", ("pad.png", encoded("white"), "image/png"))],
        data={"config": "string"},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "'string'" in detail
    assert "spec" in detail, "고칠 수 있게 예시가 함께 나와야 한다"


def test_bad_config_is_400(client) -> None:
    response = post_read(client, "white", overrides={"no_such_key": 1})
    assert response.status_code == 400


def test_overrides_do_not_leak_between_requests(client) -> None:
    before = client.get("/config").json()

    changed = only(
        post_read(client, "white", overrides={"spec": SPEC_NAME, "grid": {"rows": 3, "cols": 3}})
    )
    assert changed["grid_shape"] == [3, 3]

    assert client.get("/config").json() == before
    assert only(post_read(client, "white"))["grid_shape"] == [8, 11]


# ---------------------------------------------------------------------------
# 일관성
# ---------------------------------------------------------------------------


def strip_timing(body: dict) -> dict:
    """매번 달라지는 시간 항목을 걷어낸다."""
    body = json.loads(json.dumps(body))
    body.pop("summary")
    for result in body["results"]:
        result.pop("elapsed_ms")
        result["summary"] = result["summary"].rsplit(" · ", 1)[0]
    return body


def test_repeated_requests_agree(client) -> None:
    params = vary(BASE, dust_coverage=0.15)
    first = post_read(client, "white", params, include_cells=True, detail=True).json()
    second = post_read(client, "white", params, include_cells=True, detail=True).json()
    assert strip_timing(first) == strip_timing(second)


def test_read_by_path(client, tmp_path) -> None:
    image, _ = synthesize(SPEC, "white", vary(BASE, dust_coverage=0.1))
    path = tmp_path / "pad.png"
    cv2.imwrite(str(path), image)

    response = client.post(
        "/read/path",
        json={"paths": [str(path)], "tone": "white", "config": {"spec": SPEC_NAME}},
    )
    assert response.status_code == 200
    assert only(response)["success"]


def test_read_by_path_reports_missing_file_per_item(client, tmp_path) -> None:
    """없는 파일 하나 때문에 나머지가 죽으면 안 된다."""
    image, _ = synthesize(SPEC, "white", vary(BASE, dust_coverage=0.1))
    path = tmp_path / "pad.png"
    cv2.imwrite(str(path), image)

    body = client.post(
        "/read/path",
        json={
            "paths": [str(path), str(tmp_path / "nope.png")],
            "tone": "white",
            "config": {"spec": SPEC_NAME},
        },
    ).json()

    assert body["count"] == 2 and body["succeeded"] == 1
    assert body["results"][0]["success"] is True
    assert body["results"][1]["failure_reason"] == "invalid_image"


def test_both_read_endpoints_agree(client, tmp_path) -> None:
    """업로드와 경로 판독이 같은 값을 내는지.

    두 엔드포인트가 설정을 다른 방식으로 받으면 한쪽에서 설정이 조용히
    무시되어 다른 값이 나온다. 결과가 달라지는데 아무 오류도 안 나는 것이
    가장 나쁜 형태라 여기서 고정한다.
    """
    params = vary(BASE, dust_coverage=0.2)
    image, _ = synthesize(SPEC, "white", params)
    path = tmp_path / "pad.png"
    cv2.imwrite(str(path), image)

    uploaded = only(post_read(client, "white", params, detail=True))
    by_path = only(
        client.post(
            "/read/path",
            json={
                "paths": [str(path)],
                "tone": "white",
                "detail": True,
                "config": {"spec": SPEC_NAME},
            },
        )
    )

    assert uploaded["spec_name"] == by_path["spec_name"] == SPEC_NAME
    assert uploaded["normalization"]["method"] == by_path["normalization"]["method"]
    assert uploaded["dust_score"] == pytest.approx(by_path["dust_score"], abs=1e-9)


def test_path_request_rejects_unknown_config_key(client, tmp_path) -> None:
    image, _ = synthesize(SPEC, "white", BASE)
    path = tmp_path / "pad.png"
    cv2.imwrite(str(path), image)

    response = client.post(
        "/read/path", json={"paths": [str(path)], "config": {"grid": {"colz": 4}}}
    )
    assert response.status_code == 400


def test_core_module_does_not_import_web_framework() -> None:
    """판독 모듈은 서빙과 무관하게 쓰일 수 있어야 한다."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[1] / "src" / "padreader"
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for banned in ("fastapi", "pydantic", "uvicorn", "starlette"):
            assert banned not in text, f"{path.name} 이 {banned} 를 참조한다"
