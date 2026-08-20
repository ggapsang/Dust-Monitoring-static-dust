"""합성 촬영 이미지 생성.

실촬영 사진이 아직 없으므로, 정답이 알려진 입력을 만들어 판독기를 검증한다.
도안에 촬영 조건과 분진을 순서대로 입히는데, 그 순서가 실제 물리 순서와
같아야 검증이 의미를 갖는다.

    분진 침착 → 3차원 자세 → 조명 → 센서(게인·블랙레벨·감마) → 광학 흐림
    → 노이즈 → 압축

특히 **블랙레벨을 명시적으로 주입**한다. 관측값이 ``B0 + g*E*rho`` 라서
테두리 나눗셈으로는 ``B0`` 가 소거되지 않는다는 것이 2점 캘리브레이션을
쓰는 이유인데, 합성에 ``B0`` 가 없으면 그 차이가 드러나지 않아 검증이
헛돈다.

한계를 분명히 해 둔다. 합성은 여기 적힌 모델을 그대로 되돌려줄 뿐이다.
테두리 기반 조명 추정이 실제로 쓸 만한 정밀도인지, 흑/백 패드의 정밀도
비대칭이 얼마나 벌어지는지 같은 것은 실촬영으로만 판정할 수 있다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

import cv2
import numpy as np

from padreader.render import DEFAULT_QUIET_RATIO, render_pad
from padreader.spec import PadSpec

# 분진 반사율. 무채색이라 하나의 값으로 충분하다.
BLACK_DUST_REFLECTANCE = 0.06
WHITE_DUST_REFLECTANCE = 0.88

# 인쇄물의 실제 반사율. 도안은 0 과 255 로 그려지지만 실제 인쇄는 그렇게
# 극단적이지 않다. 무광 흑색 인쇄가 5% 안팎, 백색 용지가 85% 안팎이다.
# 0 을 그대로 쓰면 저반사면이 완전 흡수가 되어, 블랙레벨 오프셋의 영향이
# 실제보다 과장되거나 아예 0 으로 나눠지는 상황이 된다.
PRINT_DARK_REFLECTANCE = 0.05
PRINT_LIGHT_REFLECTANCE = 0.85


@dataclass
class Clump:
    """localized 뭉침 하나. 좌표는 패드 정규화 좌표."""

    x: float
    y: float
    sigma: float
    coverage: float


@dataclass
class CaptureParams:
    """한 장을 만드는 데 필요한 모든 조건.

    기본값은 '정면·균일조명·무분진·이상적 센서' 다. 검증에서는 항목 하나씩만
    흔들어 그 항목의 영향을 분리해 본다.
    """

    # --- 분진 ---
    dust_coverage: float = 0.0
    """고르게 흩뿌려진 분진의 피복률 0-1.

    **입자로 뿌린다.** 매끄러운 막으로 덮으면 localized 대비가 전혀 생기지 않아
    '주변보다 어두운 것' 을 찾는 판독 방식이 원리상 아무것도 볼 수 없다.
    실제 침착도 개별 입자가 쌓이는 것이므로 입자로 두는 편이 맞다.
    """

    dust_particle_px: int = 1
    """입자 하나의 지름. 패드 렌더 해상도 기준 픽셀.

    실제 분진은 밀가루처럼 곱다. 패드가 100mm 이고 900px 로 렌더하면 한
    픽셀이 100um 남짓이라, 입자 하나가 픽셀 하나 안팎이 된다. 1 이면 낱
    픽셀로 찍는다.
    """

    clumps: tuple[Clump, ...] = ()
    """localized 뭉침. 균일 침착 위에 더해진다."""

    # --- 자세 ---
    tilt_deg: float = 0.0
    """광축에서 기울인 각도."""

    pan_deg: float = 0.0
    """기울인 방향."""

    roll_deg: float = 0.0
    """면내 회전. 부착 자세가 조금 틀어진 것."""

    quarter_turns: int = 0
    """패드를 90도 단위로 돌려 붙인 경우 (0-3)."""

    pad_fill: float = 0.55
    """패드가 이미지 짧은 변의 몇 배를 차지하는지. 촬영 거리에 해당한다."""

    # --- 조명 ---
    light_gradient: float = 0.0
    """패드를 가로지르는 조도 변화 폭 (평균 대비 비율)."""

    light_direction_deg: float = 0.0

    # --- 센서 ---
    gain: float = 1.0
    black_level: float = 0.0
    """센서 블랙레벨 오프셋. 승산 모델을 깨뜨리는 항이다."""

    gamma: float = 1.0
    """1.0 이 아니면 선형 모델이 깨진다. 2점 캘리브레이션의 한계 확인용."""

    # --- 광학·노이즈 ---
    blur_sigma: float = 0.0
    noise_sigma: float = 0.0
    jpeg_quality: int | None = None

    # --- 장면 ---
    image_size: tuple[int, int] = (1600, 1200)
    background_level: int = 110
    background_texture: float = 0.0
    seed: int = 0


def _coverage_map(
    spec: PadSpec, params: CaptureParams, size: int, quiet_ratio: float
) -> np.ndarray:
    """패드 각 지점의 피복률 0-1.

    앵커가 보호된 규격이면 앵커 자리의 피복률을 0 으로 둔다. 라미네이트나
    투명창으로 덮어 분진이 앉지 않게 만든 상태를 흉내내는 것이며, 2점
    캘리브레이션이 성립하려면 물리적으로 이 조건이 갖춰져야 한다.
    """
    coverage = np.zeros((size, size), np.float32)

    if params.dust_coverage > 0:
        # 목표 피복률만큼 입자를 흩뿌린다. 개수는 입자 하나의 면적에서
        # 역산하고, 겹침을 감안해 조금 더 뿌린 뒤 잘라낸다.
        rng = np.random.default_rng(params.seed + 977)
        diameter = max(1, int(params.dust_particle_px))
        target = float(np.clip(params.dust_coverage, 0.0, 1.0))
        speck = np.zeros((size, size), np.uint8)

        if diameter <= 1:
            # 밀가루처럼 고운 입자. 낱 픽셀로 찍는다. 겹침을 감안해
            # 목표보다 조금 더 뿌린 뒤 실제로 덮인 비율로 맞춘다.
            count = int(size * size * -np.log(max(1.0 - target, 1e-6)))
            xs = rng.integers(0, size, count)
            ys = rng.integers(0, size, count)
            speck[ys, xs] = 1
        else:
            radius = diameter / 2.0
            per_particle = np.pi * radius * radius
            count = int(size * size * target / per_particle * 1.15)
            xs = rng.integers(0, size, count)
            ys = rng.integers(0, size, count)
            for x, y in zip(xs.tolist(), ys.tolist()):
                cv2.circle(speck, (x, y), max(1, int(round(radius))), 1, -1)

        coverage += speck.astype(np.float32)

    if params.clumps:
        ys, xs = np.mgrid[0:size, 0:size]
        unit_x = xs / size
        unit_y = ys / size
        for clump in params.clumps:
            d2 = (unit_x - clump.x) ** 2 + (unit_y - clump.y) ** 2
            coverage += clump.coverage * np.exp(-d2 / (2.0 * clump.sigma**2))

    coverage = np.clip(coverage, 0.0, 1.0)

    if spec.anchors_protected:
        pad_px = size / (1.0 + 2.0 * quiet_ratio)
        origin = size * quiet_ratio / (1.0 + 2.0 * quiet_ratio)
        for rect in spec.anchor_white + spec.anchor_black:
            x0 = int(round(origin + rect.x0 * pad_px))
            y0 = int(round(origin + rect.y0 * pad_px))
            x1 = int(round(origin + rect.x1 * pad_px))
            y1 = int(round(origin + rect.y1 * pad_px))
            coverage[y0:y1, x0:x1] = 0.0

    return coverage


def _apply_dust(pad: np.ndarray, coverage: np.ndarray, tone: str) -> np.ndarray:
    """도안 레벨을 실제 반사율로 옮긴 뒤 피복률만큼 분진을 섞는다.

    관측 포인트별 분진 색상이 정해져 있으므로, 백색 바탕 패드에는 흑색
    분진이, 흑색 바탕 패드에는 백색 분진이 앉는다. 분진 반사율이 잉크
    반사율과 거의 같다는 점이 중요하다 — 그래서 잉크는 오염되어도 값이
    거의 변하지 않는, 패드에서 유일하게 안정된 기준면이 된다.
    """
    dust = BLACK_DUST_REFLECTANCE if tone == "white" else WHITE_DUST_REFLECTANCE
    level = pad.astype(np.float32) / 255.0
    reflectance = PRINT_DARK_REFLECTANCE + level * (
        PRINT_LIGHT_REFLECTANCE - PRINT_DARK_REFLECTANCE
    )
    return (1.0 - coverage) * reflectance + coverage * dust


def _pad_corners_in_image(params: CaptureParams) -> np.ndarray:
    """3차원 자세를 거쳐 이미지에 놓인 패드 캔버스의 네 꼭짓점.

    핀홀 카메라로 실제로 투영한다. 사영변환 행렬을 아무렇게나 만들면 실제
    촬영에서 나올 수 없는 왜곡이 생겨, 판독기가 통과해도 의미가 없다.
    """
    width, height = params.image_size
    half = 0.5
    plane = np.array(
        [[-half, -half, 0.0], [half, -half, 0.0], [half, half, 0.0], [-half, half, 0.0]]
    )

    roll = np.radians(params.roll_deg)
    rz = np.array(
        [[np.cos(roll), -np.sin(roll), 0], [np.sin(roll), np.cos(roll), 0], [0, 0, 1]]
    )

    # 기울임 축은 pan 방향에 수직인 축이다.
    pan = np.radians(params.pan_deg)
    axis = np.array([np.cos(pan), np.sin(pan), 0.0])
    tilt = np.radians(params.tilt_deg)
    kx = np.array(
        [[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]]
    )
    r_tilt = np.eye(3) + np.sin(tilt) * kx + (1 - np.cos(tilt)) * (kx @ kx)

    points = plane @ (r_tilt @ rz).T

    # 카메라 거리와 초점거리를 함께 잡아 원하는 화면 점유율을 만든다.
    short_side = min(width, height)
    focal = short_side * 1.4
    distance = focal / (params.pad_fill * short_side) if params.pad_fill > 0 else 3.0
    points = points + np.array([0.0, 0.0, distance])

    projected = points[:, :2] / points[:, 2:3] * focal
    return projected + np.array([width / 2.0, height / 2.0])


def _light_field(shape: tuple[int, int], params: CaptureParams) -> np.ndarray:
    """장면에 걸리는 조도. 평균 1 의 평면이다."""
    height, width = shape
    if params.light_gradient == 0.0:
        return np.ones(shape, np.float32)

    ys, xs = np.mgrid[0:height, 0:width]
    angle = np.radians(params.light_direction_deg)
    # 이미지 대각 길이로 정규화해 방향과 무관하게 같은 폭이 되게 한다.
    projection = (xs - width / 2) * np.cos(angle) + (ys - height / 2) * np.sin(angle)
    projection = projection / (np.hypot(width, height) / 2.0)
    return (1.0 + params.light_gradient * projection).astype(np.float32)


def synthesize(
    spec: PadSpec,
    tone: str,
    params: CaptureParams,
    point_id: str = "1078",
    pad_px: int = 900,
) -> tuple[np.ndarray, np.ndarray]:
    """합성 촬영 이미지와 패드 외곽 네 꼭짓점의 정답 좌표를 반환한다.

    Returns
    -------
    (BGR 이미지, (4,2) 꼭짓점). 꼭짓점은 시계방향 TL, TR, BR, BL 이며
    **패드를 돌려 붙인 뒤의** 방향 기준이다.
    """
    rng = np.random.default_rng(params.seed)
    width, height = params.image_size

    pad = render_pad(spec, tone, point_id=point_id, pad_px=pad_px, channels=1)

    # 분진은 패드 좌표계에 앉는다. 부착 자세로 돌리는 것은 그 다음이다.
    # 순서를 바꾸면 앵커 보호 영역이 실제 앵커를 벗어난다.
    coverage = _coverage_map(spec, params, pad.shape[0], DEFAULT_QUIET_RATIO)
    reflectance = _apply_dust(pad, coverage, tone)
    reflectance = np.rot90(reflectance, params.quarter_turns % 4).copy()

    # 장면 배경. 패드가 놓인 바닥이다.
    background = np.full((height, width), params.background_level / 255.0, np.float32)
    if params.background_texture > 0:
        background += rng.normal(0, params.background_texture, background.shape).astype(
            np.float32
        )

    canvas_corners = _pad_corners_in_image(params)
    size = pad.shape[0]
    src = np.array([[0, 0], [size, 0], [size, size], [0, size]], np.float32)
    matrix = cv2.getPerspectiveTransform(src, canvas_corners.astype(np.float32))

    warped = cv2.warpPerspective(
        reflectance, matrix, (width, height), flags=cv2.INTER_LINEAR
    )
    mask = cv2.warpPerspective(
        np.ones_like(reflectance), matrix, (width, height), flags=cv2.INTER_LINEAR
    )
    scene = warped * mask + background * (1.0 - mask)

    # 조명 -> 센서. 관측값 = 블랙레벨 + 게인 * 조도 * 반사율.
    scene = scene * _light_field(scene.shape, params)
    if params.gamma != 1.0:
        scene = np.power(np.clip(scene, 0.0, None), 1.0 / params.gamma)
    scene = params.black_level / 255.0 + params.gain * scene

    image = np.clip(scene * 255.0, 0, 255)

    if params.blur_sigma > 0:
        image = cv2.GaussianBlur(image, (0, 0), params.blur_sigma)
    if params.noise_sigma > 0:
        image = image + rng.normal(0, params.noise_sigma, image.shape)

    out = cv2.cvtColor(np.clip(image, 0, 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)

    if params.jpeg_quality is not None:
        ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, params.jpeg_quality])
        if ok:
            out = cv2.imdecode(buf, cv2.IMREAD_COLOR)

    # 정답 꼭짓점은 quiet zone 을 뺀 패드 외곽이다.
    quiet = pad_px * DEFAULT_QUIET_RATIO
    inner = np.array(
        [
            [quiet, quiet],
            [size - quiet, quiet],
            [size - quiet, size - quiet],
            [quiet, size - quiet],
        ],
        np.float32,
    )
    truth = cv2.perspectiveTransform(inner.reshape(1, 4, 2), matrix).reshape(4, 2)
    return out, truth


def vary(base: CaptureParams, **changes) -> CaptureParams:
    """조건 하나만 바꾼 파라미터. 검증에서 변수를 분리할 때 쓴다."""
    return replace(base, **changes)


def expected_soiling(tone: str, coverage: float) -> float:
    """주어진 피복률에서 판독기가 내놓아야 할 오염도.

    판독기는 앵커(또는 잉크) 기준 반사율을 쓰므로, 원 반사율이 아니라
    **인쇄 흑/백을 0/1 로 놓은 척도**로 환산해야 비교가 맞는다.

        rho_hat = (rho - dark) / (light - dark)

    분진이 섞인 반사율 ``rho = (1-c)*rho_bg + c*rho_dust`` 를 넣고, 오염
    방향을 톤에 맞춰 뒤집으면 기대값이 나온다.
    """
    background = PRINT_LIGHT_REFLECTANCE if tone == "white" else PRINT_DARK_REFLECTANCE
    dust = BLACK_DUST_REFLECTANCE if tone == "white" else WHITE_DUST_REFLECTANCE
    rho = (1.0 - coverage) * background + coverage * dust
    span = PRINT_LIGHT_REFLECTANCE - PRINT_DARK_REFLECTANCE
    rho_hat = (rho - PRINT_DARK_REFLECTANCE) / span
    return 1.0 - rho_hat if tone == "white" else rho_hat
