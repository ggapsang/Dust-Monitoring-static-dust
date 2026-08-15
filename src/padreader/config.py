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
    min_pad_area_ratio: float = 0.005
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


@dataclass
class OrientConfig:
    min_margin: float | None = None


@dataclass
class QualityConfig:
    max_edge_rise_ratio: float | None = None
    min_tenengrad: float | None = None
    max_saturated_bright_ratio: float | None = None
    max_saturated_dark_ratio: float | None = None
    min_pad_size_px: float | None = None
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
    """국소 배경을 추정할 창 크기. 패드 한 변 대비 비율.

    이 창보다 큰 덩어리는 배경으로 흡수되어 가장자리만 잡힌다. 반대로 창을
    키우면 조명 변화를 얼룩으로 오인하기 시작한다. 실증에서 실제 덩어리
    크기를 보고 정할 값이다.
    """

    depth_threshold: float = 0.05
    """국소 배경보다 이만큼 어두우면 분진으로 본다. 테두리를 1 로 놓은
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
class ScoreConfig:
    uniform_reference: float | None = None
    """고름 스코어가 1.0 이 되는 값. ``null`` 이면 원값을 그대로 0-1 로
    자른다. 실증 분포를 보고 정할 값이다."""

    localized_reference: float | None = None
    """국소 스코어가 1.0 이 되는 값. 덩어리의 면적 비율 x 짙기다."""


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
class TargetIdConfig:
    enabled: bool = True
    digits: int | None = None
    font_dir: str | None = None
    """TARGET_ID 판독에 쓸 폰트를 찾을 폴더.

    이 폴더에 TTF/OTF 파일이 있으면 그것으로 숫자 템플릿을 그려 맞춘다.
    실제 인쇄에 쓴 폰트를 여기 넣어 두면 판독률이 올라간다. 폴더가 없거나
    비어 있으면 내장 스트로크 폰트로 돈다 — 지금까지와 같은 동작이다.

    상대 경로는 **설정 파일이 있는 폴더** 기준으로 푼다. 어디서 실행하든
    같은 곳을 가리켜야 하기 때문이다. ``/config`` 응답에는 푼 결과가 절대
    경로로 나오므로, 파일을 어디에 둬야 하는지 그걸로 확인하면 된다.
    """


@dataclass
class ServiceConfig:
    host: str = "0.0.0.0"
    port: int = 8911


@dataclass
class Config:
    spec: str = "v2"
    pad_size_px: int = 1120
    pad_size_mm: float | None = None
    detect: DetectConfig = field(default_factory=DetectConfig)
    orient: OrientConfig = field(default_factory=OrientConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)
    normalize: NormalizeConfig = field(default_factory=NormalizeConfig)
    dust: DustConfig = field(default_factory=DustConfig)
    score: ScoreConfig = field(default_factory=ScoreConfig)
    visualize: VisualizeConfig = field(default_factory=VisualizeConfig)
    lines: LinesConfig = field(default_factory=LinesConfig)
    target_id: TargetIdConfig = field(default_factory=TargetIdConfig)
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
    "score": ScoreConfig,
    "visualize": VisualizeConfig,
    "lines": LinesConfig,
    "target_id": TargetIdConfig,
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
        if cfg.target_id.font_dir:
            cfg.target_id.font_dir = str(
                (src.parent / cfg.target_id.font_dir).resolve()
            )
    return cfg.merged(overrides)
