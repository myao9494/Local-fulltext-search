"""
Flet ランチャーの検索結果アクションが OS 差分なく Web アプリ互換に動くことを検証する。
"""

from typing import Any

from launcher_app.config import LauncherConfig
from launcher_app.models import SearchResultItem
from launcher_app.ui.app import LauncherApp


class StubWindow:
    """
    Flet window に必要な属性だけを持つテスト用スタブ。
    """

    minimized = False


class StubPage:
    """
    LauncherApp のアクションテストに必要な page API だけを持つ。
    """

    def __init__(self) -> None:
        self.window = StubWindow()
        self.update_count = 0
        self.tasks: list[Any] = []

    def update(self) -> None:
        self.update_count += 1

    def run_task(self, task: Any) -> None:
        self.tasks.append(task)


class StubClient:
    """
    アクセス数更新と保存場所表示の呼び出し内容を記録する。
    """

    def __init__(self) -> None:
        self.clicked_file_ids: list[int] = []
        self.opened_locations: list[str] = []

    def record_click(self, file_id: int) -> int:
        self.clicked_file_ids.append(file_id)
        return 1

    def open_location(self, path: str) -> None:
        self.opened_locations.append(path)


class StubStatus:
    """
    Flet Text の value だけを持つテスト用スタブ。
    """

    value = ""


class StubResultsColumn:
    """
    Flet Column の controls だけを持つテスト用スタブ。
    """

    controls: list[Any] = []


def make_item(*, result_kind: str = "file", full_path: str = "/tmp/docs/a b.md") -> SearchResultItem:
    """
    アクションテスト用の検索結果を作る。
    """
    return SearchResultItem(
        file_id=42,
        result_kind=result_kind,
        target_path=full_path,
        file_name=full_path.rsplit("/", maxsplit=1)[-1],
        full_path=full_path,
        file_ext=".md",
        created_at="2026-01-01T00:00:00",
        mtime="2026-01-01T00:00:00",
        click_count=0,
        snippet="",
    )


def test_select_and_open_uses_web_url(monkeypatch: Any) -> None:
    """
    Flet 版もローカルファイルではなく Web アプリ互換 URL を既定ブラウザで開く。
    """
    opened_urls: list[str] = []
    client = StubClient()
    config = LauncherConfig(web_base_url="http://localhost:8001")
    app = LauncherApp(StubPage(), client, config)  # type: ignore[arg-type]

    monkeypatch.setattr("webbrowser.open", lambda url: opened_urls.append(url))

    app._select_and_open(make_item())

    assert opened_urls == ["http://localhost:8001/api/fullpath?path=%2Ftmp%2Fdocs%2Fa%20b.md"]
    assert client.clicked_file_ids == [42]
    assert app.is_hidden is True


def test_reveal_selected_uses_backend_open_location() -> None:
    """
    Flet 版も保存場所表示はバックエンド API に合わせる。
    """
    client = StubClient()
    app = LauncherApp(StubPage(), client, LauncherConfig())  # type: ignore[arg-type]
    app.results = [make_item(full_path="/tmp/docs/a.md")]

    app._reveal_selected()

    assert client.opened_locations == ["/tmp/docs"]
    assert app.is_hidden is True


def test_search_error_message_survives_async_dispatch() -> None:
    """
    バックグラウンド検索エラーは非同期 UI 更新時にもメッセージを失わない。
    """
    page = StubPage()
    app = LauncherApp(page, StubClient(), LauncherConfig())  # type: ignore[arg-type]
    app.status = StubStatus()
    app.results_column = StubResultsColumn()
    app.search_sequence = 1

    class FailingClient:
        def search(self, query: str, *, limit: int) -> None:
            raise RuntimeError("backend down")

    app.client = FailingClient()  # type: ignore[assignment]

    app._search("alpha", 1)

    coroutine = page.tasks[0]()
    try:
        coroutine.send(None)
    except StopIteration:
        pass

    assert app.status.value == "検索に失敗しました: backend down"
