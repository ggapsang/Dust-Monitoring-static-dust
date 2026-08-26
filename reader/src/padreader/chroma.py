"""유채색(마젠타) 패드 판독 경로.

기존 흑백 패드는 그대로 둔다 - 이 모듈은 그 옆에 나란히 놓일 새 경로다.
``dust.py``/``score.py`` 는 건드리지 않는다.

패드 종류는 정합 후 측정 여백의 채도로 자동 판별한다(``classify_pad_type``).
유채색으로 판별되면 2톤 앵커로 R·G·B 채널을 각각 정규화하고(``channel_normalize``),
그 위에서 명도·채도 두 필드를 낸다. 셋 다 자유 파라미터(임계값·가중치·차수)가
없다 - 노출 영역 전체를 부호 그대로 합산하고 제곱근을 씌울 뿐이다. 원리는
``optical_density.py`` 의 광학밀도 지표와 같다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import cv2
import numpy as np

from .config import DetectConfig
from .detect import Detection
from .geometry import order_corners, quad_area, quad_side_lengths, quads_overlap
from .result import ChromaFieldScore, FailureReason
from .spec import PadSpec, Rect

PAD_TYPE_SATURATION_THRESHOLD = 0.35
"""유채색/무채색 판별 기준. 정합 후 측정 여백의 (max-min)/max 중앙값.

실측 근거 - 무채색(백/흑) 패드 실촬영 77장(136개 검출)의 여백 채도 중앙값은
최소 0.0098, 중앙값 0.0379, **최댓값 0.1843** 이었다(JPEG 압축·카메라 화이트
밸런스 잔차가 전부 포함된 실촬영 값). 마젠타 인쇄 자체의 채도는 도안 원본에서
직접 재면 1.0(RGB 236,0,140) 이다. 두 쪽 사이에 5배 이상의 틈이 있으므로,
그 중간의 어느 값을 잡아도 오분류 위험이 작다. 무채색 실측 최댓값(0.184)의
약 2배, 잉크 채도(1.0)의 1/3 이하인 0.35 를 잡았다.

**한계**: 무채색 쪽은 실촬영으로 뒷받침되지만, 유채색 쪽은 실제 카메라로
찍은 마젠타 패드 사진이 아직 없어 도안 원본(인쇄값 그대로, 카메라 노출·
렌즈·JPEG 압축 영향 없음)으로만 확인했다. 실촬영이 확보되면 이 값을
재검토해야 한다.
"""

DETECT_SATURATION_THRESHOLD = 0.35
"""색으로 패드를 찾을 때(``detect_pads_chroma``) 후보 마스크의 채도 하한.

위 판별 기준과 **같은 값에서 출발하지만 다른 상수다.** 둘을 한 값으로 묶으면
한쪽을 손볼 수 없다 - 검출은 후보를 넉넉히 내는 쪽이 유리해 내리고 싶고,
판별은 무채색 실촬영 최댓값(0.184)보다 확실히 위에 있어야 해서 내릴 수 없다.
묶어 두고 0.15 로 내리면 진짜 무채색 패드가 유채색으로 판별된다.
"""

MAGENTA_HUE_DEG = 324.0
"""프로세스 마젠타(RGB 236,0,140)의 색상각(HSV H, 도). 도안 원본에서 직접
계산했다: max=R 이므로 H = 60*(((G-B)/Δ) mod 6) = 60*(((0-140)/236) mod 6)."""

HUE_TOLERANCE_DEG = 40.0
"""채도만으로 유채색 후보를 고르면 마젠타가 아닌 다른 색(주황 파티션,
간판 등)까지 걸린다 - 실촬영에서 실제로 걸렸다(사무실 파티션의 채도 높은
주황색 원단). 색상각까지 같이 보면 걸러진다. 여유폭은 카메라 화이트밸런스·
조명 색온도가 색상각을 어느 정도 돌릴 수 있다는 점을 감안해 넉넉히 뒀다 -
40도면 순수 주황(약 30도)과는 264도 이상 떨어져 있어 여전히 걸러진다."""


def _mean_hue_deg(bgr_pixels: np.ndarray) -> float:
    """화소 무리의 평균 색상각(도). 원형량이라 단순 평균이 아니라 벡터 평균을 쓴다."""
    hsv = cv2.cvtColor(bgr_pixels.reshape(-1, 1, 3).astype(np.uint8), cv2.COLOR_BGR2HSV)
    hue_deg = hsv[..., 0].astype(np.float64).ravel() * 2.0  # OpenCV H 는 0-179 (실제 각의 절반)
    radians = np.deg2rad(hue_deg)
    mean_angle = math.atan2(float(np.sin(radians).mean()), float(np.cos(radians).mean()))
    return math.degrees(mean_angle) % 360.0


def _hue_distance_deg(a: float, b: float) -> float:
    diff = abs(a - b) % 360.0
    return min(diff, 360.0 - diff)


def classify_pad_type(
    rectified_bgr: np.ndarray,
    spec: PadSpec,
    pad_size_px: int,
    threshold: float = PAD_TYPE_SATURATION_THRESHOLD,
) -> tuple[str, float]:
    """정합 후 측정 여백의 채도 중앙값으로 ``mono``/``chroma`` 를 가른다.

    앵커 정규화 전 원값으로 본다 - 판별 자체가 정규화의 성패에 앞서야 하고,
    분진이 앉아도(무채색이므로) 채도가 오르는 방향이 아니라 이 판별은
    분진 유무에 흔들리지 않는다.
    """
    mx0, my0, mx1, my1 = spec.margin.to_pixels(pad_size_px)
    region = rectified_bgr[my0:my1, mx0:mx1].astype(np.float64)
    b, g, r = region[..., 0], region[..., 1], region[..., 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    # HSV 의 S 정의와 같다: max=0(순흑)이면 채도 미정 -> 0으로 둔다.
    saturation = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    median_saturation = float(np.median(saturation))
    pad_type = "chroma" if median_saturation > threshold else "mono"
    return pad_type, median_saturation


def detect_pads_chroma(
    bgr: np.ndarray,
    spec: PadSpec,
    cfg: DetectConfig,
    saturation_threshold: float = DETECT_SATURATION_THRESHOLD,
) -> list[Detection]:
    """유채색 패드를 색으로 직접 찾는다. 무채색 검출(``detect.py``)과 별개
    경로다 - 그쪽은 건드리지 않는다.

    무채색 검출은 "잉크 링 + 그 안의 밝은 구멍"을 밝기로 가른다. 유채색
    패드가 어둡게 찍히면(마젠타가 잉크만큼 어두워지면) 그 밝기 대비가
    사라져 링을 못 찾는다 - 실측 사례: 명도 13~33 인데 채도는 0.91.
    채도는 밝기와 무관하게 남으므로, 측정면(고르게 채도가 높은 사각
    덩어리)을 직접 찾는다.

    측정면의 네 꼭짓점만 찾으면 패드 외곽은 역산으로 나온다 - 측정 여백이
    패드 전체 좌표계에서 정확히 어느 정규화 사각형인지(``spec.margin``)는
    이미 규격에 있고, 같은 평면이므로 사영변환도 하나다.
    """
    height, width = bgr.shape[:2]
    b, g, r = bgr[..., 0].astype(np.float64), bgr[..., 1].astype(np.float64), bgr[..., 2].astype(np.float64)
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    saturation = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)
    mask = (saturation > saturation_threshold).astype(np.uint8) * 255

    # 렌즈 색수차 등 가는 잡음을 지운다. 커널을 사진 짧은 변 대비 비율로
    # 잡아 해상도에 무관하게 만든다 - detect.py 의 local_block_ratio 와
    # 같은 방식.
    k = max(3, int(round(min(height, width) * 0.01)))
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    total_area = float(height * width)
    candidates: list[Detection] = []
    for contour in contours:
        area = cv2.contourArea(contour)
        ratio = area / total_area
        if ratio < cfg.min_pad_area_ratio or ratio > cfg.max_pad_area_ratio:
            continue

        quad = _fit_quad(contour)
        if quad is None:
            continue
        quad_a = quad_area(quad)
        # cfg.detect.min_solidity(기본 0.85)는 잉크 링 컨투어 기준이라 색
        # 덩어리에는 너무 빡빡하다 - 실측 진짜 패드가 0.70 이었다(기울어져
        # 찍히거나 반사로 한쪽이 깎이면 충전율이 자연히 낮아진다). 진짜와
        # 가짜를 가르는 건 이 값이 아니라 아래 색상각이므로, 여기서는 순전한
        # 잡음(가는 띠 등)만 거르는 낮은 바닥으로 둔다.
        if quad_a <= 0 or area / quad_a < 0.5:
            continue

        # 채도만으로는 마젠타 아닌 다른 유채색 물체(주황 파티션 등)도 걸린다.
        # 이 컨투어 안 화소의 평균 색상각이 마젠타에서 너무 멀면 버린다.
        fill = np.zeros((height, width), np.uint8)
        cv2.drawContours(fill, [contour], -1, 255, thickness=cv2.FILLED)
        region_pixels = bgr[fill > 0]
        if region_pixels.size == 0:
            continue
        hue = _mean_hue_deg(region_pixels)
        if _hue_distance_deg(hue, MAGENTA_HUE_DEG) > HUE_TOLERANCE_DEG:
            continue

        # 역산의 기준은 ``spec.margin`` 이 아니라 ``spec.margin_raw`` 다.
        # 눈에 보이는 유채색 덩어리는 인쇄된 측정면 전체이고, ``spec.margin``
        # 은 거기서 판독 여유(margin_inset)만큼 안으로 물러난 사각형이라
        # 서로 다른 물건이다. 물러난 쪽으로 역산하면 패드 외곽이 그 비율만큼
        # 부풀어 앵커 자리가 통째로 밀린다.
        margin_corners = _align_to_margin(order_corners(quad), spec.margin_raw)
        pad_corners = _pad_corners_from_margin(margin_corners, spec.margin_raw)
        candidates.append(
            Detection(
                corners=pad_corners,
                coarse_corners=pad_corners,
                area=quad_area(pad_corners),
                # 잉크 링 변 적합이 아니라 색 덩어리 컨투어에서 나온 것이라
                # 그 진단값이 없다 - 뒤(회전 판정·품질 게이트)에서 어차피
                # 다시 검증한다.
                edge_sample_counts=(0, 0, 0, 0),
                edge_residuals=(0.0, 0.0, 0.0, 0.0),
            )
        )

    # 같은 물체가 잡음 때문에 컨투어 두 개로 갈라지는 경우가 있다(가는 다리로
    # 이어진 덩어리가 열림 연산에서 끊기는 등). 큰 것부터 채워 겹치면 버린다
    # - detect.py 가 이진화 임계를 여럿 시도할 때 쓰는 것과 같은 판정
    # (geometry.quads_overlap: 중심 거리가 작은 쪽 크기의 절반 안이면 같은
    # 물체로 본다).
    candidates.sort(key=lambda d: -d.area)
    out: list[Detection] = []
    for det in candidates:
        if not any(quads_overlap(det.corners, det.area, o.corners, o.area) for o in out):
            out.append(det)
    return out


_APPROX_RATIOS = (0.01, 0.015, 0.02, 0.03, 0.045, 0.06, 0.08)
"""사각형 근사에 시도할 오차 허용치(둘레 대비). 촘촘한 것부터 본다."""


def _fit_quad(contour: np.ndarray) -> np.ndarray | None:
    """색 덩어리 윤곽에 볼록 사각형을 맞춘다. 못 맞추면 ``None``.

    **``cv2.minAreaRect`` 를 쓰면 안 된다.** 그것이 낼 수 있는 것은 회전된
    직사각형뿐인데, 비스듬히 찍힌 사각형은 원근 때문에 사다리꼴이다. 사다리꼴에
    직사각형을 맞추면 꼭짓점이 틀어지고, 그 꼭짓점으로 정면 보정을 하면 원근이
    펴지지 않은 채 평행사변형으로 남는다 - 실촬영에서 실제로 그렇게 나왔다.
    측정면이 안 펴지면 그 위에서 역산한 패드 외곽도, 앵커 자리도 전부 밀린다.

    ``approxPolyDP`` 로 "정확히 4점" 을 한 번만 요구하는 것도 안 된다. 인쇄
    카드 모서리가 살짝 둥글거나 JPEG 잡음이 꼭짓점을 하나 더 만들면(실측:
    오각형으로 잡힌 사례) 진짜 패드가 통째로 버려진다.

    그래서 두 가지를 같이 쓴다 - 먼저 **볼록 껍질**을 씌워 오목한 잡음을
    없애고(색 덩어리가 한쪽이 깎여 들어가도 사각형 판정이 흔들리지 않는다),
    그 위에서 오차 허용치를 촘촘한 것부터 늘려 가며 4점이 나오는 첫 값을
    쓴다. 사다리꼴 그대로를 살리면서 잡음에는 관대해진다.
    """
    hull = cv2.convexHull(contour)
    peri = cv2.arcLength(hull, True)
    if peri <= 0:
        return None
    for ratio in _APPROX_RATIOS:
        approx = cv2.approxPolyDP(hull, ratio * peri, True)
        if len(approx) == 4 and cv2.isContourConvex(approx):
            return approx.reshape(4, 2).astype(np.float64)
    return None


def _align_to_margin(quad: np.ndarray, margin_rect: Rect) -> np.ndarray:
    """검출한 사각형의 꼭짓점 순서를 측정면 규격의 가로·세로에 맞춘다.

    ``order_corners`` 가 주는 것은 **사진 좌표계의** 좌상단부터다. 그런데 패드가
    사진 안에서 90도 돌아가 있으면 사진의 좌상단 꼭짓점은 측정면 규격의
    좌상단이 아니다. 측정면은 정사각형이 아니라(가로:세로 = 0.8822:0.6286 =
    1.40) 이 어긋남이 그대로 역산에 들어가면 좌표계가 파괴된다 - 실촬영에서
    역산된 패드 외곽의 네 변이 [317, 214, 111, 595] 로 나왔다. 정사각형이어야
    할 것이 5:1 이 된 것이다.

    돌아간 것은 흔한 일이다. ``cv2.imread`` 는 EXIF 회전을 반영하지 않으므로,
    가로로 든 카메라로 찍어도 원시 배열은 세로다.

    가로세로 어느 쪽이 규격의 가로인지는 **비율로 정해진다.** 한 칸 돌린 쪽이
    규격 종횡비에 더 가까우면 그쪽을 쓴다. 로그로 견주는 이유는 2배 늘어난
    것과 절반으로 준 것을 같은 크기의 어긋남으로 보기 위해서다.

    180도 어긋남은 여기서 풀지 않는다. 사각형을 반 바퀴 돌려도 종횡비가 같아
    이 방법으로는 가릴 수 없고, 뒤따르는 회전 판정(``orient.py``)이 모서리
    블록을 보고 바로잡는 몫이다.
    """
    sides = quad_side_lengths(quad)
    horizontal = (sides[0] + sides[2]) / 2.0
    vertical = (sides[1] + sides[3]) / 2.0
    if horizontal <= 0 or vertical <= 0:
        return quad
    want = margin_rect.width / margin_rect.height
    got = horizontal / vertical
    if abs(math.log(got / want)) > abs(math.log(1.0 / (got * want))):
        return np.roll(quad, -1, axis=0)
    return quad


def _pad_corners_from_margin(margin_corners_photo: np.ndarray, margin_rect: Rect) -> np.ndarray:
    """측정 여백의 사진 좌표 네 꼭짓점 -> 패드 외곽 네 꼭짓점.

    측정 여백과 패드 외곽은 같은 평면 위의 두 사각형이라 사영변환이 하나로
    통한다. 여백의 정규화 좌표(``margin_rect``)에서 사진 좌표로 가는 변환을
    구하면, 그 변환을 패드 외곽의 정규화 좌표 (0,0)-(1,1) 에 그대로 적용해
    외곽의 사진 좌표를 얻는다.
    """
    src = np.array(
        [
            [margin_rect.x0, margin_rect.y0],
            [margin_rect.x1, margin_rect.y0],
            [margin_rect.x1, margin_rect.y1],
            [margin_rect.x0, margin_rect.y1],
        ],
        dtype=np.float32,
    )
    dst = margin_corners_photo.astype(np.float32)
    transform = cv2.getPerspectiveTransform(src, dst)
    pad_norm = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], dtype=np.float32).reshape(-1, 1, 2)
    pad_photo = cv2.perspectiveTransform(pad_norm, transform).reshape(4, 2)
    return pad_photo.astype(np.float64)


@dataclass
class ChannelNormalization:
    reflectance: np.ndarray | None
    """채널별(B,G,R) 정규화 반사율. 정합 이미지 전체 크기, float64.
    흑색 앵커=0, 백색 앵커=1 이 되도록 선형 사상했다. 실패했으면 ``None``."""

    anchor_values: dict[str, list[float]]
    """{"white": [R,G,B], "black": [R,G,B]} - 두 앵커 패치의 raw 관측값(중앙값)."""

    anchor_contrast: float
    """``흰 앵커 - 검은 앵커`` 의 채널 평균(raw 0-255 척도). 정규화의 분모다.

    **실패해도 낸다.** 값이 음수면 앵커 자리를 흑백 반대로 짚고 있다는 뜻이고,
    0 에 가까우면 두 자리가 같은 것을 재고 있다는 뜻이다 - 어느 쪽이든 좌표가
    실물 도안과 어긋났다는 신호라, 사유 이름만으로는 알 수 없는 것을 알려
    준다. 실제로 이 값이 없어서 좌표 오류를 노출 문제로 오진했다.
    """

    failure: FailureReason | None


def channel_normalize(
    rectified_bgr: np.ndarray, pad_size_px: int, spec: PadSpec
) -> ChannelNormalization:
    """2톤 앵커로 R·G·B 를 채널마다 ``(값-흑) / (백-흑)`` 정규화.

    앵커 좌표는 넘겨받은 ``spec`` 의 것을 쓴다. 예전에는 ``V2_PROTECTED`` 를
    코드에 박아 두었는데, 그 규격은 이 저장소의 생성기가 그리는 도안이지
    현장에 붙은 실물 도안이 아니었다. 실물은 앵커 흑백이 반대라 분모가 음수가
    되어 유채색 판독이 전부 실패했다. 규격은 인자로 받는다.

    **실패해도 앵커 실측값과 대비는 채워서 돌려준다.** 판정만 돌려주면 왜
    실패했는지 밖에서 알 방법이 없다.
    """
    height, width = rectified_bgr.shape[:2]

    def sample(rects) -> np.ndarray:
        pixels = []
        for rect in rects:
            x0, y0, x1, y1 = rect.to_pixels(pad_size_px)
            x1, y1 = min(x1, width), min(y1, height)
            patch = rectified_bgr[y0:y1, x0:x1].astype(np.float64)
            pixels.append(patch.reshape(-1, 3))
        return np.concatenate(pixels, axis=0)

    white_px = sample(spec.anchor_white)
    black_px = sample(spec.anchor_black)

    white_med = np.median(white_px, axis=0)  # (B,G,R)
    black_med = np.median(black_px, axis=0)
    span = white_med - black_med

    def out(reflectance, failure) -> ChannelNormalization:
        return ChannelNormalization(
            reflectance=reflectance,
            anchor_values={
                "white": [float(v) for v in white_med[::-1]],  # B,G,R -> R,G,B 순으로 보고
                "black": [float(v) for v in black_med[::-1]],
            },
            anchor_contrast=float(span.mean()),
            failure=failure,
        )

    # 클리핑 검사. 8bit 하드 한계 그대로(포화 255, 바닥 0) - 임계값이 아니라
    # 카메라 양자화 한계 자체다.
    #
    # 두 묶음을 각각 본다. 한 식에 묶어 화소 단위로 OR 하면 두 묶음의 화소 수가
    # 같아야만 성립하는데, 앵커 사각형이 정규화 좌표라 좌우가 1px 다르게
    # 반올림되면 그 순간 터진다. 애초에 흰 앵커의 3번 화소와 검은 앵커의 3번
    # 화소를 짝지을 이유도 없다.
    def clipped(pixels: np.ndarray) -> bool:
        return bool(((pixels <= 0) | (pixels >= 255)).any())

    if clipped(white_px) or clipped(black_px):
        return out(None, FailureReason.ANCHOR_CLIPPED)
    if np.any(span <= 0):
        return out(None, FailureReason.ANCHOR_SPAN_INVALID)

    return out((rectified_bgr.astype(np.float64) - black_med) / span, None)


def luma_of(reflectance: np.ndarray) -> np.ndarray:
    """Rec.601 명도. ``0.299R + 0.587G + 0.114B``."""
    b, g, r = reflectance[..., 0], reflectance[..., 1], reflectance[..., 2]
    return 0.299 * r + 0.587 * g + 0.114 * b


def saturation_of(reflectance: np.ndarray) -> np.ndarray:
    """``(max-min)/max`` = HSV 의 S. 채널별 정규화 반사율 위에서 잰다.

    반사율이 앵커 폭을 살짝 벗어나는 화소(잡음, 또는 앵커보다 더 밝거나
    어두운 실제 반사율)가 있을 수 있으므로 [0, 2] 로 눌러 극단값이 나눗셈을
    폭주시키지 않게 한다. 위 여유는 넉넉히 두어 정상 범위(0-1)를 자르지
    않는다.
    """
    clipped = np.clip(reflectance, 0.0, 2.0)
    b, g, r = clipped[..., 0], clipped[..., 1], clipped[..., 2]
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    return np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0.0)


def field_score(diff: np.ndarray, measurable: np.ndarray) -> ChromaFieldScore:
    """부호 그대로 합산 -> 평균 -> 제곱근. 임계값 없음. 음수 평균은 0."""
    n = int(measurable.sum())
    if n == 0:
        return ChromaFieldScore()
    total = float(diff[measurable].sum())
    mean = total / n
    score = math.sqrt(mean) if mean > 0 else 0.0
    return ChromaFieldScore(sum=total, mean=mean, score=score)


def clipped_ratio(raw_bgr_region: np.ndarray) -> dict[str, float]:
    """노출 영역 전체에서 채널별 포화·바닥 화소 비율. 진단용, 판정에 안 쓴다."""
    b, g, r = raw_bgr_region[..., 0], raw_bgr_region[..., 1], raw_bgr_region[..., 2]
    n = raw_bgr_region.shape[0] * raw_bgr_region.shape[1]
    out = {}
    for name, ch in (("r", r), ("g", g), ("b", b)):
        out[name] = float(((ch <= 0) | (ch >= 255)).sum() / n) if n else 0.0
    return out


def channel_means(reflectance_region: np.ndarray, measurable: np.ndarray) -> dict[str, float]:
    """노출 영역의 채널별 평균(정규화 반사율)."""
    n = int(measurable.sum())
    if n == 0:
        return {"r": None, "g": None, "b": None}
    b, g, r = reflectance_region[..., 0], reflectance_region[..., 1], reflectance_region[..., 2]
    return {
        "r": float(r[measurable].mean()),
        "g": float(g[measurable].mean()),
        "b": float(b[measurable].mean()),
    }
