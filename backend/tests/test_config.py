"""
起動設定の既定値を検証する。
意図せず既定ポートが変わらないように固定する。
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.config import Settings


def test_settings_default_bind_port_is_8079() -> None:
    """
    環境変数未指定時の既定ポートは 8079 を使う。
    """
    assert Settings.model_fields["bind_port"].default == 8079


def test_settings_default_database_path_does_not_depend_on_cwd(monkeypatch, tmp_path: Path) -> None:
    """
    既定の DB 保存先は起動ディレクトリに依存せず、backend/data/search.db を指す。
    """
    expected = (Path(__file__).resolve().parents[1] / "data" / "search.db").resolve()

    monkeypatch.chdir(tmp_path)

    assert Settings().database_path == expected


def test_settings_default_exclude_keywords_path_does_not_depend_on_cwd(monkeypatch, tmp_path: Path) -> None:
    """
    既定の除外キーワード保存先は起動ディレクトリに依存せず、backend/data/exclude_keywords.txt を指す。
    """
    expected = (Path(__file__).resolve().parents[1] / "data" / "exclude_keywords.txt").resolve()

    monkeypatch.chdir(tmp_path)

    assert Settings().exclude_keywords_path == expected


def test_settings_relative_paths_are_normalized_to_absolute_stable_locations() -> None:
    """
    設定のパス項目は相対指定でも内部では安定した絶対パスへ正規化する。
    """
    backend_dir = Path(__file__).resolve().parents[1]
    project_root_dir = backend_dir.parent
    settings = Settings(
        data_dir=Path("custom-data"),
        frontend_dist_dir=Path("frontend/custom-dist"),
    )

    assert settings.data_dir == (backend_dir / "custom-data").resolve()
    assert settings.frontend_dist_dir == (project_root_dir / "frontend/custom-dist").resolve()


def test_settings_database_name_rejects_path_segments() -> None:
    """
    database_name にはファイル名のみを許可し、パス区切りを混入させない。
    """
    with pytest.raises(ValidationError):
        Settings(database_name="../search.db")


def test_settings_exclude_keywords_name_rejects_path_segments() -> None:
    """
    exclude_keywords_name にはファイル名のみを許可し、パス区切りを混入させない。
    """
    with pytest.raises(ValidationError):
        Settings(exclude_keywords_name="../exclude_keywords.txt")
