"""
macOS ランチャーが Web アプリと同じ検索結果 URL を生成することを検証する。
"""

from launcher_app.models import SearchResultItem
from launcher_app.ui.urls import (
    folder_path_for_item,
    folder_web_url_for_item,
    full_path_web_url,
    primary_web_url_for_item,
    uses_system_file_launcher,
    open_with_system_file_launcher,
)


def make_item(*, result_kind: str, full_path: str) -> SearchResultItem:
    """
    URL 生成テスト用の最小検索結果を作る。
    """
    return SearchResultItem(
        file_id=1,
        result_kind=result_kind,
        source_type="local",
        target_path=full_path,
        file_name=full_path.rsplit("/", maxsplit=1)[-1],
        full_path=full_path,
        file_ext=".md",
        created_at="2026-01-01T00:00:00",
        mtime="2026-01-01T00:00:00",
        click_count=0,
        snippet="",
    )


def test_file_primary_url_matches_web_app_fullpath_url() -> None:
    """
    ファイル結果は Web アプリ同様 /api/fullpath?path=... を開く。
    """
    item = make_item(result_kind="file", full_path="/tmp/docs/a b.md")

    assert primary_web_url_for_item(item) == "http://127.0.0.1:8001/api/fullpath?path=%2Ftmp%2Fdocs%2Fa%20b.md"


def test_open_hub_base_trailing_slash_is_normalized() -> None:
    """環境変数の末尾スラッシュでOpen契約URLが二重スラッシュにならない。"""
    item = make_item(result_kind="file", full_path="/tmp/docs/a.md")

    assert primary_web_url_for_item(item, "http://127.0.0.1:8001/") == "http://127.0.0.1:8001/api/fullpath?path=%2Ftmp%2Fdocs%2Fa.md"


def test_folder_primary_url_matches_web_app_folder_url() -> None:
    """
    フォルダ結果は Web アプリ同様 /?path=... を開く。
    """
    item = make_item(result_kind="folder", full_path="/tmp/docs")

    assert primary_web_url_for_item(item) == "http://127.0.0.1:8001/?path=%2Ftmp%2Fdocs"


def test_folder_link_uses_parent_for_file_results() -> None:
    """
    ファイル結果のフォルダリンクは親フォルダ URL を開く。
    """
    item = make_item(result_kind="file", full_path="/tmp/docs/a.md")

    assert folder_path_for_item(item) == "/tmp/docs"
    assert folder_web_url_for_item(item) == "http://127.0.0.1:8001/?path=%2Ftmp%2Fdocs"


def test_full_path_url_encodes_japanese_paths() -> None:
    """
    日本語パスも Web アプリの encodeURIComponent 相当でエンコードする。
    """
    assert full_path_web_url("/tmp/明和高校.md") == (
        "http://127.0.0.1:8001/api/fullpath?path=%2Ftmp%2F%E6%98%8E%E5%92%8C%E9%AB%98%E6%A0%A1.md"
    )


def test_python_and_batch_results_bypass_the_open_hub() -> None:
    """スクリプト・実行ファイル・ショートカットは8001のOpenハブでなくOSに渡す。"""
    assert uses_system_file_launcher("C:/scripts/start.PY") is True
    assert uses_system_file_launcher("C:/scripts/start.bat") is True
    assert uses_system_file_launcher("C:/tools/app.exe") is True
    assert uses_system_file_launcher("C:/shortcuts/app.lnk") is True
    assert uses_system_file_launcher("C:/docs/readme.md") is False


def test_windows_script_launcher_uses_parent_as_current_directory(monkeypatch) -> None:
    """Windowsの関連付け起動ではスクリプトの親フォルダをcurrent dirにする。"""
    started: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr("subprocess.Popen", lambda command, **kwargs: started.append((command, kwargs)))

    open_with_system_file_launcher("C:/work/scripts/job.bat")

    assert started == [(["cmd", "/c", "start", "", "/d", "C:/work/scripts", "C:/work/scripts/job.bat"], {})]
