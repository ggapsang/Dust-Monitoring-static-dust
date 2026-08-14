"""참조 패드 판독 모듈.

관측 포인트에 부착한 참조 패드를 찍은 이미지 1장을 받아, 패드에 얼마나
분진이 침착되었는지를 나타내는 스코어와 판독 부가 정보를 낸다.

측정 원리는 침착 분진 측정에 쓰이는 sticky pad 방법론과 같다. 규정된
표면에 분진을 포집한 뒤 반사율 저하를 재는 방식이며, 원 방법이 반사계로
읽는 것을 카메라로 읽는다는 점만 다르다.

학습 요소를 쓰지 않는다. 전 경로가 기하와 통계 연산이라 판독 근거가
설명 가능하다.

스코어는 **기준 사진 대비 차이**다. 패드 부착 직후 깨끗할 때 찍은 사진과
이후 순회 때 찍은 사진을 같은 처리로 돌린 뒤 칸별로 뺀다. 두 사진은 같은
관측 포인트에서 같은 카메라로 찍은 것을 전제한다.

이 모듈은 상태를 갖지 않는다. 시계열 추세, 교체 판정, 알람은 이 모듈을
호출하는 상위 계층이 맡는다.

    >>> from padreader import read_pad
    >>> result = read_pad("patrol.jpg", "clean.jpg", pad_tone="white")
    >>> result.dust_score
"""

from .config import Config, load_config
from .pipeline import read_pad
from .result import (
    Cell,
    Dispersion,
    ExclusionReason,
    FailureReason,
    LineContrast,
    NormalizationInfo,
    PadReadResult,
    QualityMetrics,
    TargetIdStatus,
)
from .spec import LEGACY, V2, PadSpec, get_spec

__all__ = [
    "Cell",
    "Config",
    "Dispersion",
    "ExclusionReason",
    "FailureReason",
    "LEGACY",
    "LineContrast",
    "NormalizationInfo",
    "PadReadResult",
    "PadSpec",
    "QualityMetrics",
    "TargetIdStatus",
    "V2",
    "get_spec",
    "load_config",
    "read_pad",
]
