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
    opacity = 1

    async def center(self) -> None:
        return None

    async def to_front(self) -> None:
        return None


class StubPage:
    """
    LauncherApp のアクションテストに必要な page API だけを持つ。
    """

    def __init__(self) -> None:
        self.window = StubWindow()
        self.update_count = 0
        self.tasks: list[Any] = []
        self.clipboard_text = ""

    def update(self) -> None:
        self.update_count += 1

    def run_task(self, task: Any) -> None:
        self.tasks.append(task)

    def set_clipboard(self, text: str) -> None:
        self.clipboard_text = text


class StubClipboard:
    """
    Flet 0.84 Clipboard の set API だけを持つスタブ。
    """

    def __init__(self) -> None:
        self.text = ""

    def set(self, text: str) -> None:
        self.text = text


class StubAsyncClipboard:
    """
    Flet 0.84 と同じ async set API を持つスタブ。
    """

    def __init__(self) -> None:
        self.text = ""

    async def set(self, text: str) -> None:
        self.text = text


class StubPageWithClipboardObject:
    """
    page.set_clipboard がない環境で page.clipboard.set を使うことを検証する。
    """

    def __init__(self) -> None:
        self.window = StubWindow()
        self.clipboard = StubClipboard()
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
        self.opened_gantt_task_ids: list[int] = []
        self.created_tasks: list[dict[str, Any]] = []

    def record_click(self, file_id: int) -> int:
        self.clicked_file_ids.append(file_id)
        return 1

    def open_location(self, path: str) -> None:
        self.opened_locations.append(path)

    def open_gantt_task_input(self, task_id: int) -> None:
        self.opened_gantt_task_ids.append(task_id)

    def create_gantt_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.created_tasks.append(payload)
        return {"id": 101}

    def get_app_settings(self) -> dict[str, Any]:
        return {"gantt_parent": 8}


class StubStatus:
    """
    Flet Text の value だけを持つテスト用スタブ。
    """

    value = ""


class StubValueControl:
    """
    value と focus だけを持つ入力欄スタブ。
    """

    def __init__(self, value: str = "") -> None:
        self.value = value
        self.focus_count = 0

    def focus(self) -> None:
        self.focus_count += 1


class StubResultsColumn:
    """
    Flet Column の controls だけを持つテスト用スタブ。
    """

    def __init__(self) -> None:
        self.controls: list[Any] = []
        self.scroll_calls: list[dict[str, Any]] = []

    def scroll_to(self, **kwargs: Any) -> None:
        self.scroll_calls.append(kwargs)


class AsyncWindow:
    """
    再表示時の非同期ウィンドウ操作順を記録する。
    """

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls
        self.minimized = True
        self.opacity = 0

    async def center(self) -> None:
        self.calls.append("center")

    async def to_front(self) -> None:
        self.calls.append("to_front")


class AsyncQuery:
    """
    非同期 focus の呼び出し順を記録する。
    """

    def __init__(self, calls: list[str]) -> None:
        self.calls = calls

    async def focus(self) -> None:
        self.calls.append("focus")


def make_item(*, result_kind: str = "file", full_path: str = "/tmp/docs/a b.md") -> SearchResultItem:
    """
    アクションテスト用の検索結果を作る。
    """
    return SearchResultItem(
        file_id=42,
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


def make_gantt_item(*, task_id: int = 42) -> SearchResultItem:
    """
    gantt 検索結果のアクションテスト用アイテムを作る。
    """
    return SearchResultItem(
        file_id=-abs(task_id),
        result_kind="task",
        source_type="gantt",
        target_path=f"gantt://tasks/{task_id}",
        file_name=f"task {task_id}",
        full_path=f"gantt://tasks/{task_id}",
        file_ext="",
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


def test_copy_path_sets_clipboard_text(monkeypatch: Any) -> None:
    """
    フルパスボタンは検索結果の full_path をクリップボードへ入れる。
    """
    page = StubPage()
    app = LauncherApp(page, StubClient(), LauncherConfig())  # type: ignore[arg-type]
    app.status = StubStatus()
    monkeypatch.setattr("platform.system", lambda: "Linux")

    app._copy_path(make_item(full_path="C:/docs/a.md"))

    assert page.clipboard_text == "C:/docs/a.md"
    assert app.status.value == "クリップボードにコピーしました"


def test_copy_path_uses_flet_clipboard_set_when_page_helper_is_missing(monkeypatch: Any) -> None:
    """
    Flet 0.84 では page.clipboard.set でフルパスをコピーする。
    """
    page = StubPageWithClipboardObject()
    app = LauncherApp(page, StubClient(), LauncherConfig())  # type: ignore[arg-type]
    app.status = StubStatus()
    monkeypatch.setattr("platform.system", lambda: "Linux")

    app._copy_path(make_item(full_path="C:/docs/a.md"))

    assert page.clipboard.text == "C:/docs/a.md"
    assert app.status.value == "クリップボードにコピーしました"


def test_copy_path_schedules_async_flet_clipboard_set(monkeypatch: Any) -> None:
    """
    Flet 0.84 の async clipboard.set は page.run_task に渡して実行する。
    """
    page = StubPageWithClipboardObject()
    page.clipboard = StubAsyncClipboard()
    app = LauncherApp(page, StubClient(), LauncherConfig())  # type: ignore[arg-type]
    app.status = StubStatus()
    monkeypatch.setattr("platform.system", lambda: "Linux")

    app._copy_path(make_item(full_path="C:/docs/a.md"))

    coroutine = page.tasks[0]()
    try:
        coroutine.send(None)
    except StopIteration:
        pass

    assert page.clipboard.text == "C:/docs/a.md"


def test_copy_path_uses_windows_set_clipboard(monkeypatch: Any) -> None:
    """
    Windows では OS クリップボードにも Set-Clipboard でコピーする。
    """
    captured: dict[str, Any] = {}
    page = StubPageWithClipboardObject()
    app = LauncherApp(page, StubClient(), LauncherConfig())  # type: ignore[arg-type]
    app.status = StubStatus()
    monkeypatch.setattr("platform.system", lambda: "Windows")

    def fake_run(command: list[str], **kwargs: Any) -> object:
        captured["command"] = command
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr("subprocess.run", fake_run)

    app._copy_path(make_item(full_path="C:/docs/a.md"))

    assert captured["command"] == ["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"]
    assert captured["kwargs"]["input"] == "C:/docs/a.md"


def test_open_folder_url_uses_web_folder_link(monkeypatch: Any) -> None:
    """
    フォルダを開くボタンは Web アプリのフォルダ URL を開く。
    """
    opened_urls: list[str] = []
    app = LauncherApp(StubPage(), StubClient(), LauncherConfig(web_base_url="http://localhost:8001"))  # type: ignore[arg-type]
    monkeypatch.setattr("webbrowser.open", lambda url: opened_urls.append(url))

    app._open_folder_url(make_item(full_path="C:/docs/a.md"))

    assert opened_urls == ["http://localhost:8001/?path=C%3A%2Fdocs"]


def test_move_selection_scrolls_to_selected_result() -> None:
    """
    下キー移動時は見えている末尾側に選択カードが入るよう offset で追従する。
    """
    results_column = StubResultsColumn()
    app = LauncherApp(StubPage(), StubClient(), LauncherConfig())  # type: ignore[arg-type]
    app.status = StubStatus()
    app.results_column = results_column
    app.results = [make_item(full_path="/tmp/docs/a.md"), make_item(full_path="/tmp/docs/b.md")]
    app._render_results = lambda: None  # type: ignore[method-assign]

    app._move_selection(1)

    assert app.selected_index == 1
    assert results_column.scroll_calls == [{"offset": 0, "duration": 120}]


def test_move_selection_refocuses_query_for_enter_open() -> None:
    """
    Windows Flet で結果側へフォーカスが移っても、矢印移動後は Enter 起動できるよう検索欄へ戻す。
    """
    page = StubPage()
    focus_calls: list[str] = []
    app = LauncherApp(page, StubClient(), LauncherConfig())  # type: ignore[arg-type]
    app.query = type("Query", (), {"focus": lambda self: focus_calls.append("focus")})()
    app.status = StubStatus()
    app.results_column = StubResultsColumn()
    app.results = [make_item(full_path="/tmp/docs/a.md"), make_item(full_path="/tmp/docs/b.md")]
    app._render_results = lambda: None  # type: ignore[method-assign]

    app._move_selection(1)

    assert focus_calls == []
    assert len(page.tasks) == 1
    page.tasks[0]()
    assert focus_calls == ["focus"]


def test_render_results_refocuses_query_after_list_update() -> None:
    """
    検索結果の再描画後は Windows Flet のフォーカスずれに備えて検索欄へ戻す。
    """
    page = StubPage()
    focus_calls: list[str] = []
    app = LauncherApp(page, StubClient(), LauncherConfig())  # type: ignore[arg-type]
    app.query = type("Query", (), {"focus": lambda self: focus_calls.append("focus")})()
    app.results_column = StubResultsColumn()
    app.results = []
    app.active_screen = "search"
    app.is_hidden = False

    app._render_results()

    assert len(page.tasks) == 1
    page.tasks[0]()
    assert focus_calls == ["focus"]


def test_show_window_restores_focus_after_window_is_front() -> None:
    """
    再表示時は to_front 完了後に検索欄へ focus し、Enter 起動を復旧する。
    """
    calls: list[str] = []
    page = StubPage()
    page.window = AsyncWindow(calls)
    app = LauncherApp(page, StubClient(), LauncherConfig())  # type: ignore[arg-type]
    app.query = AsyncQuery(calls)

    app._show_window()
    coroutine = page.tasks[0]()
    try:
        coroutine.send(None)
    except StopIteration:
        pass

    assert calls == ["center", "to_front", "focus"]
    assert app.is_hidden is False


def test_keyboard_accepts_windows_flet_arrow_and_enter_names(monkeypatch: Any) -> None:
    """
    Windows の Flet で揺れるキー名でも矢印選択と Enter 起動を処理する。
    """
    opened_urls: list[str] = []
    client = StubClient()
    app = LauncherApp(StubPage(), client, LauncherConfig(web_base_url="http://localhost:8001"))  # type: ignore[arg-type]
    app.status = StubStatus()
    app.results_column = StubResultsColumn()
    app.results = [make_item(full_path="/tmp/docs/a.md"), make_item(full_path="/tmp/docs/b.md")]
    app._render_results = lambda: None  # type: ignore[method-assign]
    monkeypatch.setattr("webbrowser.open", lambda url: opened_urls.append(url))

    app._on_keyboard(type("Event", (), {"key": "ArrowDown"})())
    app._on_keyboard(type("Event", (), {"key": "Numpad Enter"})())

    assert app.selected_index == 1
    assert opened_urls == ["http://localhost:8001/api/fullpath?path=%2Ftmp%2Fdocs%2Fb.md"]
    assert client.clicked_file_ids == [42]


def test_enter_open_is_deduplicated_when_submit_and_keyboard_both_fire(monkeypatch: Any) -> None:
    """
    TextField submit と page keyboard の両方が同じ Enter を拾っても URL は 1 回だけ開く。
    """
    now = 100.0
    opened_urls: list[str] = []
    client = StubClient()
    app = LauncherApp(StubPage(), client, LauncherConfig(web_base_url="http://localhost:8001"))  # type: ignore[arg-type]
    app.status = StubStatus()
    app.results = [make_item(full_path="/tmp/docs/a.md")]
    monkeypatch.setattr("webbrowser.open", lambda url: opened_urls.append(url))
    monkeypatch.setattr("launcher_app.ui.app.time.monotonic", lambda: now)

    app._open_selected()
    app._on_keyboard(type("Event", (), {"key": "Enter"})())

    assert opened_urls == ["http://localhost:8001/api/fullpath?path=%2Ftmp%2Fdocs%2Fa.md"]
    assert client.clicked_file_ids == [42]


def test_global_enter_fallback_runs_open_on_ui_thread() -> None:
    """
    pynput の Enter フォールバックは UI スレッドへ戻して選択結果を開く。
    """
    page = StubPage()
    opened: list[bool] = []
    app = LauncherApp(page, StubClient(), LauncherConfig())  # type: ignore[arg-type]
    app._open_selected = lambda: opened.append(True)  # type: ignore[method-assign]

    app._open_selected_from_global_enter()
    coroutine = page.tasks[0]()
    try:
        coroutine.send(None)
    except StopIteration:
        pass

    assert opened == [True]


def test_global_enter_fallback_only_enabled_on_visible_search_screen() -> None:
    """
    グローバル Enter の保険は検索画面が表示中のときだけ有効にする。
    """
    app = LauncherApp(StubPage(), StubClient(), LauncherConfig())  # type: ignore[arg-type]

    assert app._global_enter_enabled() is True

    app.is_hidden = True
    assert app._global_enter_enabled() is False

    app.is_hidden = False
    app.active_screen = "memo"
    assert app._global_enter_enabled() is False


def test_select_and_open_deduplicates_same_item_like_click(monkeypatch: Any) -> None:
    """
    Enter 由来の複数イベントが直接起動処理へ来ても、クリックと同じく 1 回だけ開く。
    """
    now = 100.0
    opened_urls: list[str] = []
    client = StubClient()
    app = LauncherApp(StubPage(), client, LauncherConfig(web_base_url="http://localhost:8001"))  # type: ignore[arg-type]
    monkeypatch.setattr("webbrowser.open", lambda url: opened_urls.append(url))
    monkeypatch.setattr("launcher_app.ui.app.time.monotonic", lambda: now)

    item = make_item(full_path="/tmp/docs/a.md")
    app._select_and_open(item)
    app._select_and_open(item)

    assert opened_urls == ["http://localhost:8001/api/fullpath?path=%2Ftmp%2Fdocs%2Fa.md"]
    assert client.clicked_file_ids == [42]


def test_select_and_open_deduplicates_gantt_task_input() -> None:
    """
    Flet と pynput の Enter が両方届いても gantt タスク入力は 1 回だけ開く。
    """
    client = StubClient()
    app = LauncherApp(StubPage(), client, LauncherConfig())  # type: ignore[arg-type]
    item = make_gantt_item(task_id=123)

    app._select_and_open(item)
    app._select_and_open(item)

    assert client.opened_gantt_task_ids == [123]


def test_keyboard_accepts_windows_flet_escape_name() -> None:
    """
    Windows の Flet で Escape の表記が揺れてもランチャーを隠す。
    """
    page = StubPage()
    app = LauncherApp(page, StubClient(), LauncherConfig())  # type: ignore[arg-type]

    app._on_keyboard(type("Event", (), {"key": "Esc"})())

    assert app.is_hidden is True
    assert page.window.minimized is True


def test_move_selection_scrolls_down_after_visible_window() -> None:
    """
    表示可能件数を超えて下へ移動したらリストを下方向へスクロールする。
    """
    results_column = StubResultsColumn()
    app = LauncherApp(StubPage(), StubClient(), LauncherConfig())  # type: ignore[arg-type]
    app.status = StubStatus()
    app.results_column = results_column
    app.results = [make_item(full_path=f"/tmp/docs/{index}.md") for index in range(8)]
    app.selected_index = 3
    app._render_results = lambda: None  # type: ignore[method-assign]

    app._move_selection(1)

    assert app.selected_index == 4
    assert results_column.scroll_calls == [{"offset": 82, "duration": 120}]


def test_clear_search_resets_query_results_and_status() -> None:
    """
    クリアボタンは検索語・結果・選択状態・ステータスを初期化する。
    """
    page = StubPage()
    app = LauncherApp(page, StubClient(), LauncherConfig())  # type: ignore[arg-type]
    app.query = type("Query", (), {"value": "alpha", "focus": lambda self: None})()
    app.status = StubStatus()
    app.status.value = "2 件"
    app.results_column = StubResultsColumn()
    app.results = [make_item(full_path="/tmp/docs/a.md")]
    app.selected_index = 1

    app._clear_search()

    assert app.query.value == ""
    assert app.results == []
    assert app.selected_index == 0
    assert app.status.value == ""


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
        def search(self, query: str, *, limit: int, include_gantt_tasks: bool = False) -> None:
            raise RuntimeError("backend down")

    app.client = FailingClient()  # type: ignore[assignment]

    app._search("alpha", 1)

    coroutine = page.tasks[0]()
    try:
        coroutine.send(None)
    except StopIteration:
        pass

    assert app.status.value == "検索に失敗しました: backend down"


def test_tab_switches_to_memo_screen_and_enter_creates_gantt_task(monkeypatch: Any) -> None:
    """
    Tab でメモ画面へ切り替え、Enter で gantt タスク作成 API に送信する。
    """
    client = StubClient()
    config = LauncherConfig(gantt_parent=5)
    app = LauncherApp(StubPage(), client, config)  # type: ignore[arg-type]
    app.status = StubStatus()
    app.memo_status = StubStatus()
    app.query = StubValueControl()
    app.memo_field = StubValueControl("AI テストタスク\nAPI ガイドから作成したメモ")
    app.memo_parent_label = StubStatus()
    app.search_area = type("Area", (), {"visible": True})()
    app.memo_area = type("Area", (), {"visible": False})()
    monkeypatch.setattr("launcher_app.gantt_task.date", type("DateModule", (), {"today": staticmethod(lambda: __import__("datetime").date(2026, 5, 18))}))

    app._on_keyboard(type("Event", (), {"key": "Tab"})())
    app._on_keyboard(type("Event", (), {"key": "Enter"})())

    assert app.active_screen == "memo"
    assert client.created_tasks[0]["text"] == "AI テストタスク"
    assert client.created_tasks[0]["memo"] == "API ガイドから作成したメモ"
    assert client.created_tasks[0]["parent"] == 8
    assert app.memo_field.value == ""
    assert app.memo_status.value == "gantt に追加しました"


def test_memo_shift_enter_inserts_newline() -> None:
    """
    メモ画面では Shift+Enter を送信ではなく改行として扱う。
    """
    app = LauncherApp(StubPage(), StubClient(), LauncherConfig())  # type: ignore[arg-type]
    app.active_screen = "memo"
    app.memo_field = StubValueControl("1行目")
    app.memo_status = StubStatus()

    app._on_keyboard(type("Event", (), {"key": "Return", "shift": True})())

    assert app.memo_field.value == "1行目\n"
