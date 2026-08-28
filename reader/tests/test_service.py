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

from padservice.app import app  # noqa: E402

SPEC_NAME = "synth_protected"
SPEC = spec.SPECS[SPEC_NAME]
BASE = CaptureParams(pad_fill=0.8, black_level=10, gain=0.95, noise_sigma=0.8, seed=5)
"""서비스 검증용 합성 촬영 조건.

``pad_fill`` 이 크다. 배포 설정(``config/default.yaml``)의
``quality.min_pad_size_px`` 가 120 이라, 화면에서 패드가 작게 잡히는 조건으로
합성하면 판독 정확도가 아니라 그 게이트를 재게 된다. 게이트 자체는
``test_pipeline`` 이 따로 다룬다.
"""


@pytest.fixture(scope="module")
def client():
    with fastapi_testclient.TestClient(app) as test_client:
        yield test_client


def encoded(tone: str, params: CaptureParams = BASE, point_id: str = "1078") -> bytes:
    image, _ = synthesize(SPEC, tone, params, point_id=point_id)
    ok, buffer = cv2.imencode(".png", image)
    assert ok
    return buffer.tobytes()


def baseline_bytes(tone: str, params: CaptureParams = BASE) -> bytes:
    """기준 사진. 같은 촬영 조건에서 분진만 없는 상태."""
    return encoded(tone, vary(params, dust_coverage=0.0, clumps=()))


def first_pad(body: dict) -> dict:
    """응답에서 패드 하나를 꺼낸다.

    예전 응답은 패드 한 장짜리 평평한 구조였는데, 한 화면에 패드가 여러 개
    찍히는 일이 실제로 생겨 ``pads`` 배열로 바뀌었다. 스코어·품질·번호는 전부
    그 안으로 내려갔다.
    """
    pads = body.get("pads") or []
    assert pads, f"패드가 없다: {body.get('failure_detail') or body.get('summary')}"
    return pads[0]


def post_read(client, tone: str, params: CaptureParams = BASE, **kwargs):
    overrides = kwargs.pop("overrides", {})
    overrides.setdefault("spec", SPEC_NAME)
    baseline = kwargs.pop("baseline", None) or baseline_bytes(tone, params)
    # tone·visualize 는 쿼리가 아니라 **폼 필드**다. 쿼리로 보내면 조용히
    # 무시되고 기본값으로 돈다.
    form = {"tone": tone, "config": json.dumps(overrides)}
    if "visualize" in kwargs:
        form["visualize"] = str(kwargs.pop("visualize")).lower()
    return client.post(
        "/read",
        params=kwargs,
        files={
            "file": ("patrol.png", encoded(tone, params), "image/png"),
            "baseline": ("clean.png", baseline, "image/png"),
        },
        data=form,
    )


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
    assert "max_edge_rise_ratio" in values["quality"]
    assert values["chroma"]["spec"] != values["spec"], "유채색 규격이 따로 있어야 한다"
    assert body["source"] is None or body["source"].endswith(".yaml")


def test_endpoints_are_only_what_was_agreed(client) -> None:
    """합의된 것 외의 경로가 늘어나 있지 않은지 고정한다."""
    paths = set(client.get("/openapi.json").json()["paths"])
    assert paths == {
        "/healthz",
        "/config",
        "/read",
        "/read/path",
        "/images/{token}/{kind}.png",
    }, sorted(paths)


@pytest.mark.parametrize("tone", ("white", "black"))
def test_read_returns_score(client, tone: str) -> None:
    body = post_read(client, tone, vary(BASE, dust_coverage=0.2)).json()
    assert body["success"], body
    pad = first_pad(body)
    assert pad["scores"]["uniform"] == pytest.approx(0.2, abs=0.05)
    assert pad["point_id"] == "1078"


# ---------------------------------------------------------------------------
# 응답을 눈으로 읽을 수 있는가
# ---------------------------------------------------------------------------


def test_default_response_is_compact(client) -> None:
    """기본 응답에 무거운 것이 딸려오지 않아야 한다."""
    body = post_read(client, "white", vary(BASE, dust_coverage=0.2)).json()
    pad = first_pad(body)

    # 유채색 진단값은 유채색 패드일 때만 실린다.
    for chroma_only in ("chroma", "luma_dark", "luma_light", "chroma_diagnostics"):
        assert pad[chroma_only] is None, chroma_only

    for key in ("success", "summary", "scores", "point_id", "verification"):
        assert pad[key] is not None, key
    assert body["elapsed_ms"] is not None


def test_response_stays_small_by_default(client) -> None:
    # 유채색 패드 시험 경로가 무채색 응답에도 pad_type/chroma* 6개 필드를
    # null 로 더한다(약 120 바이트) - 그만큼만 한도를 올렸다. optical_density
    # 도입 때 이미 한 번 올라간 값이라 여유를 좀 더 둔다.
    body = post_read(client, "white", vary(BASE, dust_coverage=0.2)).json()
    assert len(json.dumps(body)) < 1500, "기본 응답이 여전히 무겁다"


def test_summary_reads_like_a_sentence(client) -> None:
    summary = post_read(client, "white", vary(BASE, dust_coverage=0.2)).json()["summary"]
    assert "판독 성공" in summary
    assert "combined" in summary and "uniform" in summary
    assert "point_id 1078" in summary


def test_summary_explains_failure(client) -> None:
    blank = np.full((400, 600, 3), 120, np.uint8)
    ok, buffer = cv2.imencode(".png", blank)
    assert ok

    body = client.post(
        "/read",
        params={"tone": "white"},
        files={
            "file": ("blank.png", buffer.tobytes(), "image/png"),
            "baseline": ("clean.png", baseline_bytes("white"), "image/png"),
        },
    ).json()

    assert body["success"] is False
    assert body["summary"].startswith("판독 불가")
    assert "패드를 찾지 못함" in body["summary"]
    assert body["failure_reason"] == "pad_not_found"


def test_visualize_returns_image_links(client) -> None:
    """이미지는 주소로 준다. 본문에 base64 를 실으면 응답을 읽을 수 없다."""
    off = first_pad(post_read(client, "white", visualize=False).json())
    assert off["images"] is None, "끄면 이미지를 만들지 않는다"

    body = post_read(client, "white", visualize=True).json()
    pad = first_pad(body)
    assert pad["images"]["distribution"].endswith("/distribution.png")
    assert pad["images"]["rectified"].endswith("/rectified.png")
    assert len(json.dumps(body)) < 2000, "주소 대신 이미지가 실려 온 것 아닌지"


def test_image_links_actually_serve_png(client) -> None:
    pad = first_pad(post_read(client, "white", visualize=True).json())

    for kind in ("distribution", "rectified", "baseline_rectified"):
        response = client.get(pad["images"][kind])
        assert response.status_code == 200, kind
        assert response.headers["content-type"] == "image/png"

        image = cv2.imdecode(np.frombuffer(response.content, np.uint8), cv2.IMREAD_COLOR)
        assert image is not None and image.shape[0] == image.shape[1] == 1120


def test_image_link_is_stable_for_the_same_input(client) -> None:
    """같은 입력이면 같은 주소. 주소가 이미지 내용의 해시이기 때문이다."""
    first = first_pad(post_read(client, "white", visualize=True).json())
    second = first_pad(post_read(client, "white", visualize=True).json())
    assert first["images"] == second["images"]


def test_unknown_image_token_is_404(client) -> None:
    response = client.get("/images/deadbeefdeadbeef/distribution.png")
    assert response.status_code == 404
    assert "다시 판독" in response.json()["detail"]


def test_read_by_path_can_return_image_links(client, tmp_path) -> None:
    reading, baseline = write_pair(tmp_path, vary(BASE, dust_coverage=0.2))
    body = client.post(
        "/read/path",
        json={
            "path": reading,
            "baseline_path": baseline,
            "tone": "white",
            "visualize": True,
            "config": {"spec": SPEC_NAME},
        },
    ).json()
    pad = first_pad(body)
    assert pad["images"]["distribution"].endswith("/distribution.png")
    assert client.get(pad["images"]["distribution"]).status_code == 200


def test_baseline_failure_is_reported(client) -> None:
    """기준 사진을 못 읽으면 그 사실이 사유로 나와야 한다."""
    blank = np.full((400, 600, 3), 120, np.uint8)
    ok, buffer = cv2.imencode(".png", blank)
    assert ok

    body = post_read(client, "white", baseline=buffer.tobytes()).json()
    assert body["success"] is False
    assert body["failure_reason"] == "baseline_unreadable"
    assert "기준 이미지를 판독하지 못함" in body["summary"]


def test_diagnostics_ride_along_by_default(client) -> None:
    """진단값이 늘 실려 오는지.

    예전에는 ``detail``, ``include_cells`` 플래그로 켜고 껐는데, 켜야만 나오는
    값은 사고가 난 뒤에 다시 판독해야 볼 수 있다는 문제가 있었다. 지금은 무거운
    것(이미지, 구획별 값)만 빼고 진단값은 기본으로 싣는다.

    ``verification`` 은 검출한 사각형이 정말 규격대로였는지의 잔차다. 판정에
    쓰지 않지만, 실려 있어야 나중에 기준을 바꿔 다시 걸러 볼 수 있다.
    """
    pad = first_pad(post_read(client, "white").json())

    assert pad["quality"]["pad_size_px"] is not None
    assert pad["quality"]["sharpness"] is not None
    assert pad["optical_density"]["od_score"] is not None
    assert pad["verification"]["border_fit_error"] is not None
    assert pad["verification"]["point_id_agrees"] is not None


# ---------------------------------------------------------------------------
# 설정 오버라이드
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("blank", ["", "   ", "\n"])
def test_blank_config_means_no_override(client, blank: str) -> None:
    """빈 config 는 오류가 아니라 '오버라이드 없음' 이다."""
    response = client.post(
        "/read",
        params={"tone": "white"},
        files={
            "file": ("patrol.png", encoded("white"), "image/png"),
            "baseline": ("clean.png", baseline_bytes("white"), "image/png"),
        },
        data={"config": blank},
    )
    assert response.status_code == 200
    # 오버라이드가 없으면 서버 설정 그대로 돈다. 규격 이름은 응답에 없으므로
    # /config 가 알려 주는 값과 견준다.
    assert client.get("/config").json()["values"]["spec"] == "legacy"


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
        files={
            "file": ("patrol.png", encoded("white"), "image/png"),
            "baseline": ("clean.png", baseline_bytes("white"), "image/png"),
        },
        data={"config": "string"},
    )
    assert response.status_code == 400
    detail = response.json()["detail"]
    assert "'string'" in detail
    assert "dust" in detail, "고칠 수 있게 예시가 함께 나와야 한다"


def test_bad_config_is_400(client) -> None:
    assert post_read(client, "white", overrides={"no_such_key": 1}).status_code == 400


def test_overrides_do_not_leak_between_requests(client) -> None:
    """요청 오버라이드가 서버 설정을 바꾸면 안 된다."""
    before = client.get("/config").json()

    changed = post_read(
        client, "white", overrides={"spec": SPEC_NAME, "dust": {"min_blob_px": 40}}
    ).json()
    assert changed["success"], changed

    assert client.get("/config").json() == before
    assert client.get("/config").json()["values"]["dust"]["min_blob_px"] != 40


# ---------------------------------------------------------------------------
# 일관성
# ---------------------------------------------------------------------------


def strip_timing(body: dict) -> dict:
    """매번 달라지는 시간 항목을 걷어낸다."""
    body = json.loads(json.dumps(body))
    body.pop("elapsed_ms")
    body["summary"] = body["summary"].rsplit(" · ", 1)[0]
    return body


def test_repeated_requests_agree(client) -> None:
    params = vary(BASE, dust_coverage=0.15)
    first = post_read(client, "white", params).json()
    second = post_read(client, "white", params).json()
    assert strip_timing(first) == strip_timing(second)


def test_broken_upload_is_400(client) -> None:
    response = client.post(
        "/read",
        params={"tone": "white"},
        files={
            "file": ("junk.png", b"not an image", "image/png"),
            "baseline": ("clean.png", baseline_bytes("white"), "image/png"),
        },
    )
    assert response.status_code == 400


def write_pair(tmp_path, params=BASE):
    """(판독 사진 경로, 기준 사진 경로)."""
    reading, _ = synthesize(SPEC, "white", params)
    clean, _ = synthesize(SPEC, "white", vary(params, dust_coverage=0.0, clumps=()))
    reading_path = tmp_path / "patrol.png"
    baseline_path = tmp_path / "clean.png"
    cv2.imwrite(str(reading_path), reading)
    cv2.imwrite(str(baseline_path), clean)
    return str(reading_path), str(baseline_path)


def test_read_by_path(client, tmp_path) -> None:
    reading, baseline = write_pair(tmp_path, vary(BASE, dust_coverage=0.1))

    response = client.post(
        "/read/path",
        json={
            "path": reading,
            "baseline_path": baseline,
            "tone": "white",
            "config": {"spec": SPEC_NAME},
        },
    )
    assert response.status_code == 200
    assert response.json()["success"]

    missing = client.post(
        "/read/path",
        json={"path": str(tmp_path / "nope.png"), "baseline_path": baseline},
    )
    assert missing.status_code == 404


def test_read_by_path_reports_missing_baseline(client, tmp_path) -> None:
    reading, _ = write_pair(tmp_path)
    response = client.post(
        "/read/path",
        json={"path": reading, "baseline_path": str(tmp_path / "nope.png")},
    )
    assert response.status_code == 404
    assert "기준 이미지" in response.json()["detail"]


def test_both_read_endpoints_agree(client, tmp_path) -> None:
    """업로드와 경로 판독이 같은 값을 내는지.

    두 엔드포인트가 설정을 다른 방식으로 받으면 한쪽에서 설정이 조용히
    무시되어 다른 값이 나온다. 결과가 달라지는데 아무 오류도 안 나는 것이
    가장 나쁜 형태라 여기서 고정한다.
    """
    params = vary(BASE, dust_coverage=0.2)
    reading, baseline = write_pair(tmp_path, params)

    uploaded = first_pad(post_read(client, "white", params).json())
    by_path = first_pad(client.post(
        "/read/path",
        json={
            "path": reading,
            "baseline_path": baseline,
            "tone": "white",
            "config": {"spec": SPEC_NAME},
        },
    ).json())

    assert uploaded["scores"] == by_path["scores"]
    assert uploaded["quality"] == by_path["quality"]
    assert uploaded["verification"] == by_path["verification"]


def test_path_request_rejects_unknown_config_key(client, tmp_path) -> None:
    reading, baseline = write_pair(tmp_path)
    response = client.post(
        "/read/path",
        json={
            "path": reading,
            "baseline_path": baseline,
            "config": {"dust": {"colz": 4}},
        },
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
