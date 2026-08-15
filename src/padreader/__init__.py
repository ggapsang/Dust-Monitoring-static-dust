"""참조 패드 판독 모듈.

관측 포인트에 부착한 참조 패드를 찍은 이미지 1장을 받아, 패드에 얼마나
분진이 침착되었는지를 나타내는 스코어와 판독 부가 정보를 낸다.

측정 원리는 침착 분진 측정에 쓰이는 sticky pad 방법론과 같다. 규정된
표면에 분진을 포집한 뒤 반사율 저하를 재는 방식이며, 원 방법이 반사계로
읽는 것을 카메라로 읽는다는 점만 다르다.

학습 요소를 쓰지 않는다. 전 경로가 기하와 통계 연산이라 판독 근거가
설명 가능하다.

도안에서 인쇄물의 위치를 알고 있으므로 그 바깥의 여백만 본다. 여백에서
**주변보다 어두운 것**을 분진으로 판정하므로 기준 사진이 필요 없다.

스코어는 두 축으로 낸다. 고르게 오염된 정도와 한 군데가 심하게 오염된
정도는 원인도 대응도 다르기 때문이다.

이 모듈은 상태를 갖지 않는다. 시계열 추세, 교체 판정, 알람은 이 모듈을
호출하는 상위 계층이 맡는다.

    >>> from padreader import read_pad
    >>> result = read_pad("pad.jpg", pad_tone="white")
    >>> result.scores.combined
"""

from .config import Config, load_config
from .pipeline import read_pad
from .result import (
    Blob,
    DustScores,
    ExclusionReason,
    FailureReason,
    NormalizationInfo,
    PadReadResult,
    QualityMetrics,
    TargetIdStatus,
)
from .spec import LEGACY, V2, PadSpec, get_spec

__all__ = [
    "Blob",
    "Config",
    "DustScores",
    "ExclusionReason",
    "FailureReason",
    "LEGACY",
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
