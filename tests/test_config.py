"""설정 로드 검증.

임계값이 실증에서 반복 조정되므로, 어떤 값이 실제로 적용되는지가 흐려지면
안 된다. 특히 컨테이너에서는 설정을 마운트해 쓰는데 경로가 어긋나면 조용히
기본값으로 도는 사고가 나기 쉽다. 그런 상황을 실패로 만든다.
"""

from __future__ import annotations

import pytest
import yaml

from padreader.config import (
    CONFIG_ENV_VAR,
    Config,
    load_config,
    resolve_config_path,
)


@pytest.fixture(autouse=True)
def clear_env(monkeypatch):
    monkeypatch.delenv(CONFIG_ENV_VAR, raising=False)


def write(path, data: dict) -> str:
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return str(path)


def test_defaults_match_the_shipped_yaml() -> None:
    """dataclass 기본값과 config/default.yaml 이 같은 값인지.

    설정 파일을 찾지 못하면 dataclass 기본값으로 도는데, 그 둘이 다르면
    배포 형태에 따라 판독 결과가 달라진다.
    """
    from_file = load_config()
    assert from_file.to_dict() == Config().to_dict()


def test_explicit_path_wins(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(CONFIG_ENV_VAR, write(tmp_path / "env.yaml", {"pad_size_px": 800}))
    explicit = write(tmp_path / "explicit.yaml", {"pad_size_px": 640})
    assert load_config(explicit).pad_size_px == 640


def test_env_var_is_used_when_no_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv(CONFIG_ENV_VAR, write(tmp_path / "env.yaml", {"pad_size_px": 800}))
    assert load_config().pad_size_px == 800
    assert str(resolve_config_path()).endswith("env.yaml")


def test_missing_env_path_fails_loudly(tmp_path, monkeypatch) -> None:
    """환경변수가 가리키는 파일이 없으면 기본값으로 떨어지지 않는다.

    임계값이 적용되지 않은 채 정상처럼 도는 것이 가장 나쁜 결과다.
    """
    monkeypatch.setenv(CONFIG_ENV_VAR, str(tmp_path / "nope.yaml"))
    with pytest.raises(FileNotFoundError):
        load_config()


def test_missing_explicit_path_fails_loudly(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        load_config(tmp_path / "nope.yaml")


def test_unknown_key_is_rejected(tmp_path) -> None:
    """오타 난 설정 항목이 조용히 무시되면 안 된다."""
    path = write(tmp_path / "bad.yaml", {"grid": {"colz": 4}})
    with pytest.raises(ValueError, match="colz"):
        load_config(path)


def test_partial_file_keeps_other_defaults(tmp_path) -> None:
    path = write(tmp_path / "partial.yaml", {"grid": {"rows": 3}})
    cfg = load_config(path)
    assert cfg.grid.rows == 3
    assert cfg.grid.cols == Config().grid.cols
    assert cfg.score.statistic == Config().score.statistic


def test_overrides_do_not_mutate_the_source() -> None:
    """오버라이드는 새 객체를 만든다. 서비스가 요청마다 설정을 갈아끼워도
    다음 요청에 남지 않아야 한다."""
    base = load_config()
    changed = base.merged({"grid": {"rows": 2}})
    assert changed.grid.rows == 2
    assert base.grid.rows != 2
    assert base.merged(None) is base


def test_null_threshold_means_gate_is_off() -> None:
    """비워 둔 임계값은 미적용이라는 뜻이다."""
    cfg = load_config()
    assert cfg.quality.max_tilt_deg is None
    assert cfg.exclude.max_chroma is None
    assert cfg.orient.min_margin is None
