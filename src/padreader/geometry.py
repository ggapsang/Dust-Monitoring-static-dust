"""사각형 기하 유틸.

검출·회전 판정·정면 보정이 공유한다.
"""

from __future__ import annotations

import numpy as np

CORNER_NAMES: tuple[str, str, str, str] = ("tl", "tr", "br", "bl")
"""꼭짓점 순서 규약. 시계방향이며 0번이 좌상단이다.

``spec.PadSpec.corner_blocks`` 의 키와 같은 이름을 쓴다.
"""


def order_corners(points: np.ndarray) -> np.ndarray:
    """네 점을 시계방향 TL, TR, BR, BL 순으로 정렬한다.

    중심에 대한 편각으로 감는 방향을 먼저 통일하고, 그 다음 좌상단에 가장
    가까운 점을 시작점으로 돌린다. ``x+y`` 최소/최대만 쓰는 흔한 방식은
    45도 근처로 회전한 사각형에서 두 꼭짓점이 같은 값을 가져 뒤집힌다.
    """
    pts = np.asarray(points, dtype=np.float64).reshape(4, 2)
    center = pts.mean(axis=0)
    # 이미지 좌표계는 y 가 아래로 자라므로, 편각 오름차순이 곧 시계방향이다.
    angles = np.arctan2(pts[:, 1] - center[1], pts[:, 0] - center[0])
    clockwise = pts[np.argsort(angles)]

    start = int(np.argmin(clockwise.sum(axis=1)))
    return np.roll(clockwise, -start, axis=0)


def line_from_points(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """점 무리에 총최소자승 직선을 맞춘다. (방향 단위벡터, 통과점) 반환.

    ``cv2.fitLine`` 대신 직접 푸는 이유는 공분산의 고유벡터가 곧 총최소자승
    해라서 수직선에서도 특별한 처리가 필요 없기 때문이다.
    """
    pts = np.asarray(points, dtype=np.float64)
    centroid = pts.mean(axis=0)
    centered = pts - centroid
    # 가장 큰 특이값에 대응하는 방향이 점들이 가장 넓게 퍼진 방향이다.
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    return vt[0], centroid


def intersect_lines(
    d1: np.ndarray, p1: np.ndarray, d2: np.ndarray, p2: np.ndarray
) -> np.ndarray | None:
    """두 직선의 교점. 거의 평행하면 ``None``."""
    a = np.column_stack((d1, -d2))
    det = np.linalg.det(a)
    if abs(det) < 1e-9:
        return None
    t = np.linalg.solve(a, p2 - p1)
    return p1 + t[0] * d1


def quad_side_lengths(corners: np.ndarray) -> np.ndarray:
    """네 변의 길이 (TL-TR, TR-BR, BR-BL, BL-TL)."""
    rolled = np.roll(corners, -1, axis=0)
    return np.linalg.norm(rolled - corners, axis=1)


def quad_area(corners: np.ndarray) -> float:
    """신발끈 공식."""
    x, y = corners[:, 0], corners[:, 1]
    return float(0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


def quad_corner_angles(corners: np.ndarray) -> np.ndarray:
    """네 내각(도)."""
    prev = np.roll(corners, 1, axis=0)
    nxt = np.roll(corners, -1, axis=0)
    v1 = prev - corners
    v2 = nxt - corners
    cos = np.einsum("ij,ij->i", v1, v2) / (
        np.linalg.norm(v1, axis=1) * np.linalg.norm(v2, axis=1) + 1e-12
    )
    return np.degrees(np.arccos(np.clip(cos, -1.0, 1.0)))


def estimate_tilt_deg(corners: np.ndarray) -> float:
    """정면에서 얼마나 기울여 찍었는지의 프록시(도).

    카메라 내부 파라미터가 없어 호모그래피를 분해할 수 없으므로, 정사각형이
    사영으로 얼마나 일그러졌는지로 대신한다. 세 가지 왜곡을 각각 '정면
    대비 비율'로 만든 뒤 가장 큰 것을 각도로 환산한다.

    - 대변 길이비: 원근이 있으면 먼 쪽 변이 짧아진다
    - 대각선 길이비: 정사각형이면 두 대각선이 같다
    - 내각 편차: 정사각형이면 모두 90도

    반환값은 실제 촬영 각도의 하한에 가깝다. 절대 정확도가 아니라 **같은
    지표로 걸러내는 일관성**이 목적이므로, 임계값은 실증에서 이 값의 분포를
    보고 정한다.
    """
    sides = quad_side_lengths(corners)
    horizontal = max(sides[0], sides[2]) / max(min(sides[0], sides[2]), 1e-9)
    vertical = max(sides[1], sides[3]) / max(min(sides[1], sides[3]), 1e-9)

    diag = np.array(
        [
            np.linalg.norm(corners[2] - corners[0]),
            np.linalg.norm(corners[3] - corners[1]),
        ]
    )
    diagonal = diag.max() / max(diag.min(), 1e-9)

    ratio = max(horizontal, vertical, diagonal)
    # 정면이면 비율 1 -> 0도. arccos(1/ratio) 는 기울인 평면의 단축률을
    # 되돌리는 각도와 같은 형태다.
    from_ratio = np.degrees(np.arccos(np.clip(1.0 / ratio, -1.0, 1.0)))

    angle_dev = float(np.abs(quad_corner_angles(corners) - 90.0).max())
    return float(max(from_ratio, angle_dev))
