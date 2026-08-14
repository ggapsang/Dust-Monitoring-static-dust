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


@dataclass
class OrientConfig:
    min_margin: float | None = None


@dataclass
class QualityConfig:
    max_edge_rise_ratio: float | None = None
    min_tenengrad: float | None = None
    max_saturated_bright_ratio: float | None = None
    max_saturated_dark_ratio: float | None = None
    max_tilt_deg: float | None = None
    min_pad_size_px: float | None = None
    min_anchor_contrast: float | None = None
    saturation_bright_level: int = 250
    saturation_dark_level: int = 5


@dataclass
class NormalizeConfig:
    method: str = "auto"
    gradient_correction: str = "border"
    ring_samples: int = 600
    assumed_ink_reflectance_dark: float = 0.06
    assumed_ink_reflectance_light: float = 0.88


@dataclass
class GridConfig:
    rows: int = 8
    cols: int = 11
    min_valid_pixel_ratio: float = 0.9


@dataclass
class ExcludeConfig:
    chroma_metric: str = "norm"
    max_chroma: float | None = None
    max_saturated_ratio: float | None = None


@dataclass
class ScoreConfig:
    statistic: str = "p90"


@dataclass
class LinesConfig:
    enabled: bool = True


@dataclass
class TargetIdConfig:
    enabled: bool = True
    min_confidence: float = 0.55
    digits: int | None = None


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
    grid: GridConfig = field(default_factory=GridConfig)
    exclude: ExcludeConfig = field(default_factory=ExcludeConfig)
    score: ScoreConfig = field(default_factory=ScoreConfig)
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
    "grid": GridConfig,
    "exclude": ExcludeConfig,
    "score": ScoreConfig,
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
    return cfg.merged(overrides)
