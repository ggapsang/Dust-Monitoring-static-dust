"""도안 생성기 검증.

생성기가 규격대로 그리는지, 그리고 legacy 규격으로 그린 것이 실제 샘플
도안과 같은 기하를 갖는지 확인한다. 폰트는 재현할 수 없으므로 POINT_ID
모양은 비교하지 않는다.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from padreader import spec
from padreader.render import DEFAULT_QUIET_RATIO, render_pad, tone_levels

PAD_PX = 1120
QUIET_PX = int(round(PAD_PX * DEFAULT_QUIET_RATIO))
TOL_PX = 3


@pytest.fixture(params=("white", "black"))
def tone(request) -> str:
    return request.param


def gray(spec_obj: spec.PadSpec, tone: str, point_id: str = "1078") -> np.ndarray:
    img = render_pad(spec_obj, tone, point_id=point_id, pad_px=PAD_PX, channels=1)
    return img


def ink_mask(img: np.ndarray, tone: str) -> np.ndarray:
    background, ink = tone_levels(tone)
    return img < 128 if ink == 0 else img > 128


def to_canvas(norm: float) -> float:
    return QUIET_PX + norm * PAD_PX


def patch(img: np.ndarray, rect: spec.Rect, inset_px: int = 6) -> np.ndarray:
    x0, y0, x1, y1 = (int(round(to_canvas(v))) for v in (rect.x0, rect.y0, rect.x1, rect.y1))
    return img[y0 + inset_px : y1 - inset_px, x0 + inset_px : x1 - inset_px]


def test_canvas_size(tone: str) -> None:
    img = gray(spec.SYNTH, tone)
    expected = PAD_PX + 2 * QUIET_PX
    assert img.shape == (expected, expected)


def test_quiet_zone_is_background(tone: str) -> None:
    """패드 바깥이 바탕톤인지. 검출기가 테두리 바깥 경계를 잡으려면 필요하다."""
    background, _ = tone_levels(tone)
    img = gray(spec.SYNTH, tone)
    assert img[: QUIET_PX - 2, :].min() == img[: QUIET_PX - 2, :].max() == background


def test_border_thickness_matches_spec(tone: str) -> None:
    img = gray(spec.SYNTH, tone)
    mask = ink_mask(img, tone)
    center = mask[img.shape[0] // 2]
    idx = np.flatnonzero(np.diff(np.concatenate(([0], center.view(np.int8), [0]))))
    segments = list(zip(idx[0::2].tolist(), idx[1::2].tolist()))
    assert len(segments) == 2, segments

    expected = spec.BORDER_THICKNESS * PAD_PX
    for s in segments:
        assert abs((s[1] - s[0]) - expected) <= TOL_PX


def test_three_corner_blocks_drawn_br_empty(tone: str) -> None:
    """synth 는 BR 이 완전히 비어야 한다 — 선군이 더 이상 침범하지 않으므로."""
    mask = ink_mask(gray(spec.SYNTH, tone), tone)
    blocks = spec.SYNTH.corner_blocks
    for name in ("tl", "tr", "bl"):
        assert patch(mask, blocks[name]).mean() > 0.99, name
    assert patch(mask, blocks["br"]).mean() < 0.01


def test_legacy_render_reproduces_br_pollution(tone: str) -> None:
    """legacy 규격으로 그리면 실제 샘플과 같은 결함이 재현되는지.

    생성기가 규격을 제대로 반영한다는 증거다 — 결함까지 같이 나와야 한다.
    """
    mask = ink_mask(gray(spec.LEGACY, tone), tone)
    fill = patch(mask, spec.LEGACY.corner_blocks["br"]).mean()
    assert 0.3 < fill < 0.7, fill


def test_anchors_have_absolute_levels(tone: str) -> None:
    """앵커가 톤과 무관하게 절대 흑/백으로 찍히는지.

    2점 캘리브레이션 ``(I - I_black) / (I_white - I_black)`` 의 두 끝점이므로
    패드 톤에 따라 값이 흔들리면 안 된다.
    """
    img = gray(spec.SYNTH, tone)
    for rect in spec.SYNTH.anchor_white:
        assert patch(img, rect).min() == 255, "백색 앵커가 255 여야 한다"
    for rect in spec.SYNTH.anchor_black:
        assert patch(img, rect).max() == 0, "흑색 앵커가 0 이어야 한다"


def test_anchors_do_not_overlap_other_elements() -> None:
    """앵커가 다른 인쇄 요소와 겹치지 않는지 (기하 검사)."""
    s = spec.SYNTH
    others = [s.point_id_box, *s.corner_blocks.values()]
    others += [b.rect(s.line_group_x0, s.line_group_x1) for b in s.line_bars]
    for anchor in s.anchor_white + s.anchor_black:
        for other in others:
            overlap_x = min(anchor.x1, other.x1) - max(anchor.x0, other.x0)
            overlap_y = min(anchor.y1, other.y1) - max(anchor.y0, other.y0)
            assert overlap_x <= 0 or overlap_y <= 0, f"{anchor} 가 {other} 와 겹친다"


def test_margin_is_clean_in_rendered_pad(tone: str) -> None:
    """렌더된 도안에서도 측정 여백이 완전히 비어 있는지.

    ``test_spec.py`` 는 샘플 PNG 로, 여기서는 생성기 출력으로 같은 것을 본다.
    """
    background, _ = tone_levels(tone)
    for spec_obj in (spec.LEGACY, spec.SYNTH):
        img = gray(spec_obj, tone)
        region = patch(img, spec_obj.margin, inset_px=0)
        assert region.size > 0
        assert region.min() == region.max() == background, spec_obj.name


def test_point_id_stays_inside_its_box(tone: str) -> None:
    """긴 ID 를 넣어도 박스를 넘지 않는지. 넘으면 여백을 오염시킨다."""
    background, _ = tone_levels(tone)
    for target in ("1", "1078", "999999"):
        img = render_pad(spec.SYNTH, tone, point_id=target, pad_px=PAD_PX, channels=1)
        region = patch(img, spec.SYNTH.margin, inset_px=0)
        assert region.min() == region.max() == background, target


def test_render_is_deterministic() -> None:
    """같은 입력에 같은 출력. 모듈 무상태성 요건과 같은 성질이다."""
    a = render_pad(spec.SYNTH, "white", pad_px=400)
    b = render_pad(spec.SYNTH, "white", pad_px=400)
    assert np.array_equal(a, b)


def test_invalid_tone_rejected() -> None:
    with pytest.raises(ValueError):
        render_pad(spec.SYNTH, "gray")
