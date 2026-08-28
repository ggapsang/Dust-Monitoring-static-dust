"""설정 로드.

임계값과 파라미터는 코드에 하드코딩하지 않는다. 기본값은
``config/default.yaml`` 한 곳에만 있고, 이 모듈은 그것을 dataclass 로
읽어들이며 부분 오버라이드를 병합한다.

``None`` 인 임계값은 **해당 게이트를 적용하지 않는다**는 뜻이다. 산출값
자체는 항상 계산되어 결과에 담기므로, 실증에서 분포를 보고 값을 채우면 된다.
"""

from __future__ import annotations

import copy
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Mapping

import yaml

CONFIG_ENV_VAR = "PADREADER_CONFIG"
"""설정 파일 경로를 지정하는 환경변수.

컨테이너에 설치하면 패키지가 site-packages 로 들어가 소스 트리 옆의
``config/`` 를 찾을 수 없다. 임계값은 실증에서 반복 조정되므로 이미지를
다시 굽지 않고 파일만 갈아끼울 수 있어야 한다.
"""

SOURCE_TREE_CONFIG = Path(__file__).resolve().parents[2] / "config" / "default.yaml"
"""소스 트리에서 개발할 때 쓰는 기본 경로."""


@dataclass
class DetectConfig:
    blur_ksize: int = 5
    min_pad_area_ratio: float = 0.001
    """이미지 전체 면적 대비 패드 후보의 최소 면적비.

    4080x3060 화면에서 0.001 은 패드 한 변 112px 이다. 면적은 1차 거름망일
    뿐이고 뒤에 링 구조, 사각형, 채움도, 종횡비, 테두리 규격 검증이 남아
    있으므로 낮춰도 오검출로 이어지지 않는다. 반대로 높게 잡으면 멀리서 찍힌
    사진이 검출을 시작하기도 전에 잘린다.
    """
    max_pad_area_ratio: float = 0.98
    approx_epsilon_ratio: float = 0.02
    require_ring: bool = True
    min_solidity: float = 0.85
    max_aspect_ratio: float = 3.0
    edge_trim_ratio: float = 0.15
    threshold_scales: list[float] = field(
        default_factory=lambda: [1.0, 1.15, 1.3, 1.45]
    )
    """이진화 임계를 순서대로 시도할 배율. 1.0 이 오츠 그대로다.

    앞의 값으로 패드를 찾으면 뒤는 보지 않는다. 키울수록 더 옅은 잉크까지
    인쇄색으로 치므로, 패드가 밝게 찍혀 테두리가 오츠 임계에 걸린 사진을
    건진다. 대신 너무 키우면 바탕면의 옅은 얼룩까지 인쇄색이 되므로
    무한정 늘릴 값은 아니다.
    """

    local_fallback: bool = True
    """위 배율로 다 못 찾았을 때 국소 이진화로 한 번 더 볼지.

    임계 하나를 사진 전체에 쓰면 사진에서 어두운 것은 무엇이든 인쇄색이 된다.
    요철 도장면의 그늘이나 패널 이음새가 잉크로 찍히고, 거기 닿은 테두리가
    그것들과 한 덩어리가 되어 액자 모양을 잃는다. 화소마다 주변 평균과 견주면
    그 결합이 끊어진다.
    """

    local_block_ratio: float = 0.033
    """국소 이진화에서 '주변' 으로 볼 창의 크기. 사진 짧은 변 대비 비율.

    테두리 두께보다 넉넉히 커야 창 안에 잉크와 여백이 함께 들어와 대비가
    생긴다. 반대로 너무 키우면 전역 임계와 다를 바 없어진다.
    """

    local_offset: int = 25
    """주변 평균보다 이만큼 어두워야(흑색 바탕은 밝아야) 인쇄색으로 친다.

    0 에 가까우면 노이즈까지 인쇄색이 되고, 키우면 옅게 찍힌 테두리를 놓친다.
    """

    border_tolerance: float | None = 0.02
    """찾은 사각형이 바깥 테두리가 맞는지 볼 때 허용할 두께 오차.

    패드 한 변 대비 비율이다. 정면으로 편 이미지에서 잉크 띠가 네 변 모두
    0 에서 시작해 규격 두께에서 끝나야 하는데, 이보다 어긋나면 그 사각형을
    테두리로 보지 않고 안쪽 테두리로 다시 맞춘다.

    **검출이 조용히 어긋나는 것을 막는 장치다.** 패드가 벽에서 떨어져 그림자가
    지면 사각형은 찾아지지만 한쪽 변이 그림자 속으로 밀려, 검출은 성공으로
    보이는데 좌표계가 어긋난 채 틀린 값이 나온다. ``null`` 이면 확인하지 않는다.
    """

    local_open_steps: list[int] = field(default_factory=lambda: [0, 5, 9])
    """국소 이진화 결과에서 지울 선 굵기를 순서대로 시도한다. 0 은 지우지 않음.

    주변과 견줘도 진짜 어두운 선은 남는다. 벽 패널 이음새가 그렇고, 그것이
    패드에 닿아 있으면 테두리와 한 덩어리가 된다. 이음새는 가늘고 테두리는
    굵으므로 굵기로 가른다.

    값을 하나로 못 박지 않고 사다리로 둔 이유가 있다. 크게 잡으면 이음새는
    확실히 끊기지만 테두리가 얇게 찍힌 사진에서는 테두리까지 갉아 링이
    끊어진다. 지우지 않는 쪽부터 시작해 필요한 만큼만 지운다."""


@dataclass
class OrientConfig:
    min_margin: float | None = None


@dataclass
class QualityConfig:
    max_edge_rise_ratio: float | None = None
    min_tenengrad: float | None = None
    max_saturated_bright_ratio: float | None = None
    max_saturated_dark_ratio: float | None = None
    min_pad_size_px: float | None = 120
    max_pad_size_diff_ratio: float | None = None
    """기준 이미지와 판독 이미지의 패드 크기 차이 허용 비율.

    두 사진의 패드 크기가 크게 다르면 촬영 위치가 달라진 것이므로 비교가
    성립하지 않는다. ``null`` 이면 검사하지 않는다.
    """
    saturation_bright_level: int | None = None
    saturation_dark_level: int | None = None
    """포화로 볼 화소값. ``null`` 이면 포화로 제외하지 않는다.

    다른 임계값과 같은 규칙이다. 실증 사진에서 정반사가 실제로 어느 값에
    걸리는지 보고 채운다. 미리 넣어 두면 순백에 가까운 깨끗한 여백이
    통째로 제외되는 일이 생긴다.
    """


@dataclass
class NormalizeConfig:
    gradient_correction: bool = True
    ring_samples: int = 600


@dataclass
class DustConfig:
    local_window: float = 0.08
    """localized 배경을 추정할 창 크기. 패드 한 변 대비 비율.

    이 창보다 큰 덩어리는 배경으로 흡수되어 가장자리만 잡힌다. 반대로 창을
    키우면 조명 변화를 얼룩으로 오인하기 시작한다. 실증에서 실제 덩어리
    크기를 보고 정할 값이다.
    """

    depth_threshold: float = 0.05
    """localized 배경보다 이만큼 어두우면 분진으로 본다. 테두리를 1 로 놓은
    척도의 값이다. 실증 전 잠정값이다."""

    min_blob_px: int = 4
    """이보다 작은 덩어리는 노이즈로 보고 버린다."""

    clean_percentile: float = 90.0
    """여백에서 어느 분위수를 '깨끗한 톤' 으로 볼지.

    고르게 퍼진 오염을 잴 때 기준이 된다. 높일수록 가장 깨끗한 일부만
    기준으로 삼아 민감해지고, 낮출수록 둔해진다.
    """

    max_blobs: int | None = 50
    """결과에 담을 덩어리 수. 짙고 큰 순으로 자른다.

    고운 분진은 낱알이 수천 개 나오는데 전부 담으면 응답을 읽을 수 없다.
    전체 개수는 따로 알리므로 정보가 사라지지는 않는다. ``null`` 이면
    자르지 않는다.
    """


@dataclass
class ChromaConfig:
    """유채색(마젠타) 패드 판독. 시험 경로 - 기존 흑백 경로는 그대로 둔다."""

    saturation_threshold: float = 0.35
    """패드 종류 판별 기준. 정합 후 측정 여백의 (max-min)/max 중앙값이 이보다
    크면 유채색으로 본다.

    무채색 실촬영 77장(136개 검출)에서 실측한 값(최댓값 0.1843, 중앙값
    0.0379)과 마젠타 인쇄 자체의 채도(도안 원본 실측 1.0) 사이의 중간값이다 -
    유채색 쪽은 아직 실촬영으로 뒷받침되지 않았다. ``chroma.py`` 의
    ``PAD_TYPE_SATURATION_THRESHOLD`` 주석에 상세 근거가 있다.
    """

    detect_saturation_threshold: float = 0.35
    """색으로 패드를 찾을 때(``detect_pads_chroma``) 후보 마스크의 채도 하한.

    위 판별 기준과 같은 값에서 출발하지만 **다른 항목이다.** 하나로 묶으면
    한쪽을 못 건드린다 - 검출은 후보를 넉넉히 내는 쪽이 유리해 내리고 싶고,
    판별은 무채색 실촬영 최댓값(0.184) 위에 있어야 해서 못 내린다.
    """

    spec: str = "v2"
    """유채색 패드의 도안 규격. 무채색 규격(``spec``)과 따로 둔다.

    **현장 실물이 바뀌면 이 값을 바꾼다.** 지금은 ``v2``(측정면 1.40:1, 선군
    있음)이고, 개정 도안은 ``v3``(정사각 측정면, 좌우 흰 여백, 선군
    없음)다. 실물을 교체하기 전에 미리 바꾸면 붙어 있는 패드를 엉뚱한 좌표로
    재게 되고, 이미 찍어 둔 기준 사진도 못 읽는다.

    애초에 이 항목을 만든 이유도 같다. 예전에는 유채색 정규화가
    ``synth_protected`` 를 코드에 박아 썼는데, 그 규격은 이 저장소 생성기가 그리는
    도안이지 현장 실물이 아니라 앵커 흑백이 반대로 잡혀 판독이 전부 실패했다.
    규격은 코드가 아니라 설정으로 고른다.
    """


@dataclass
class ScoreConfig:
    uniform_reference: float | None = None
    """uniform 스코어가 1.0 이 되는 값. ``null`` 이면 원값을 그대로 0-1 로
    자른다. 실증 분포를 보고 정할 값이다."""

    localized_reference: float | None = None
    """localized 스코어가 1.0 이 되는 값. 덩어리의 면적 비율 x 짙기다."""


@dataclass
class VisualizeConfig:
    heat_max: float | None = 0.5
    """분포 이미지에서 빨강이 가리킬 값. 기준 대비 화소 하나의 어두워진 깊이다.

    고정해 두어야 두 장을 색으로 바로 견줄 수 있다. ``null`` 이면 사진마다
    그 안의 최댓값까지 늘려 칠하는데, 그러면 깨끗한 패드도 어딘가는 빨갛게
    나와 색만 보고는 심한지 알 수 없다. 이 값을 넘는 화소는 빨강으로 잘린다.
    """


@dataclass
class LinesConfig:
    enabled: bool = True


@dataclass
class PointIdConfig:
    enabled: bool = True
    digits: int | None = None
    font_dir: str | None = None
    """POINT_ID 판독에 쓸 폰트를 찾을 폴더.

    이 폴더에 TTF/OTF 파일이 있으면 그것으로 숫자 템플릿을 그려 맞춘다.
    실제 인쇄에 쓴 폰트를 여기 넣어 두면 판독률이 올라간다. 폴더가 없거나
    비어 있으면 내장 스트로크 폰트로 돈다 — 지금까지와 같은 동작이다.

    상대 경로는 **설정 파일이 있는 폴더** 기준으로 푼다. 어디서 실행하든
    같은 곳을 가리켜야 하기 때문이다. ``/config`` 응답에는 푼 결과가 절대
    경로로 나오므로, 파일을 어디에 둬야 하는지 그걸로 확인하면 된다.
    """

    assign_min_score: float | None = 0.15
    """닫힌 판독에서 후보에 배정할 최소 닮은 정도.

    후보 목록을 받으면 열린 판독 대신 그 안에서 고른다. 다만 후보 중 가장
    나은 것이라도 이만큼은 닮아야 배정한다 - 안 그러면 엉뚱한 자리에 붙인
    패드나 오검출된 사각형이 조용히 어느 개소로 배정된다.

    실촬영에서 맞게 읽힌 건의 값이 0.32~0.45 였다. ``null`` 이면 하한을
    두지 않는다.
    """


@dataclass
class ServiceConfig:
    host: str = "0.0.0.0"
    port: int = 8911


@dataclass
class Config:
    spec: str = "legacy"
    """설정 파일을 못 찾았을 때 쓰는 값. **``config/default.yaml`` 과 같아야 한다.**

    둘이 다르면 설정을 마운트하지 못한 배포에서 조용히 다른 규격으로 돈다 -
    규격이 다르면 앵커도 측정면도 엉뚱한 자리를 재므로, 판독이 실패하는 게
    아니라 틀린 값이 나온다. ``test_config`` 가 둘을 대조한다.
    """

    pad_size_px: int = 1120
    pad_size_mm: float | None = None
    detect: DetectConfig = field(default_factory=DetectConfig)
    orient: OrientConfig = field(default_factory=OrientConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)
    normalize: NormalizeConfig = field(default_factory=NormalizeConfig)
    dust: DustConfig = field(default_factory=DustConfig)
    chroma: ChromaConfig = field(default_factory=ChromaConfig)
    score: ScoreConfig = field(default_factory=ScoreConfig)
    visualize: VisualizeConfig = field(default_factory=VisualizeConfig)
    lines: LinesConfig = field(default_factory=LinesConfig)
    point_id: PointIdConfig = field(default_factory=PointIdConfig)
    service: ServiceConfig = field(default_factory=ServiceConfig)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def merged(self, overrides: Mapping[str, Any] | None) -> "Config":
        """부분 오버라이드를 얹은 **새** 설정을 반환한다.

        원본을 바꾸지 않는다 — 서비스 계층이 요청마다 설정을 갈아끼워도
        모듈이 상태를 갖지 않아야 하기 때문이다.
        """
        if not overrides:
            return self
        return _from_dict(_deep_merge(self.to_dict(), overrides))


# 중첩 섹션 이름 → dataclass 타입. 설정 구조가 두 단계뿐이라
# 타입 introspection 대신 이 표로 충분하다.
_SECTIONS: dict[str, type] = {
    "detect": DetectConfig,
    "orient": OrientConfig,
    "quality": QualityConfig,
    "normalize": NormalizeConfig,
    "dust": DustConfig,
    "chroma": ChromaConfig,
    "score": ScoreConfig,
    "visualize": VisualizeConfig,
    "lines": LinesConfig,
    "point_id": PointIdConfig,
    "service": ServiceConfig,
}


def _deep_merge(base: dict[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    """``over`` 를 ``base`` 위에 병합. 모르는 키는 오타이므로 즉시 실패시킨다."""
    out = copy.deepcopy(base)
    for key, value in over.items():
        if key not in out:
            raise ValueError(f"알 수 없는 설정 항목: {key!r}")
        if isinstance(value, Mapping) and isinstance(out[key], dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _from_dict(data: Mapping[str, Any]) -> Config:
    kwargs: dict[str, Any] = {}
    for key, value in data.items():
        section = _SECTIONS.get(key)
        kwargs[key] = section(**value) if section else value
    return Config(**kwargs)


def resolve_config_path(path: str | Path | None = None) -> Path | None:
    """실제로 읽을 설정 파일. 없으면 ``None``.

    인자 > 환경변수 > 소스 트리 순으로 찾는다. 환경변수로 지정했는데 그
    파일이 없으면 조용히 기본값으로 떨어지지 않고 실패시킨다 — 임계값이
    적용되지 않은 채 정상처럼 도는 것이 가장 나쁜 결과다.
    """
    if path is not None:
        resolved = Path(path)
        if not resolved.exists():
            raise FileNotFoundError(f"설정 파일이 없다: {resolved}")
        return resolved

    from_env = os.environ.get(CONFIG_ENV_VAR)
    if from_env:
        resolved = Path(from_env)
        if not resolved.exists():
            raise FileNotFoundError(
                f"{CONFIG_ENV_VAR} 가 가리키는 설정 파일이 없다: {resolved}"
            )
        return resolved

    return SOURCE_TREE_CONFIG if SOURCE_TREE_CONFIG.exists() else None


def load_config(
    path: str | Path | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> Config:
    """설정을 읽는다.

    설정 파일을 아예 찾지 못하면 dataclass 기본값으로 동작한다. 그 기본값은
    ``config/default.yaml`` 과 같은 값이므로 판독 결과가 달라지지는 않는다.
    """
    src = resolve_config_path(path)
    if src is None:
        cfg = Config()
    else:
        raw = yaml.safe_load(src.read_text(encoding="utf-8")) or {}
        cfg = _from_dict(_deep_merge(Config().to_dict(), raw))
        # 상대 경로를 여기서 한 번에 푼다. 뒤에서 쓰는 쪽이 설정 파일의
        # 위치를 몰라도 되고, /config 응답에도 푼 결과가 그대로 보인다.
        if cfg.point_id.font_dir:
            cfg.point_id.font_dir = str(
                (src.parent / cfg.point_id.font_dir).resolve()
            )
    return cfg.merged(overrides)
