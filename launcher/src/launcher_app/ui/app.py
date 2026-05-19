"""
Spotlight 風の Flet ランチャー UI を構築する。
"""

from __future__ import annotations

import inspect
import logging
import platform
import subprocess
import threading
import time
from typing import Any
import webbrowser

from launcher_app.api.client import LauncherApiClient, LauncherApiError
from launcher_app.config import LauncherConfig
from launcher_app.gantt_task import build_gantt_task_payload, normalize_parent_id
from launcher_app.models import SearchResultItem
from launcher_app.services.hotkeys import GlobalHotkeyController, hotkey_spec_for_platform
from launcher_app.ui.urls import folder_path_for_item, folder_web_url_for_item, primary_web_url_for_item
from launcher_app.utils import strip_html

logger = logging.getLogger(__name__)
WINDOW_WIDTH = 820
WINDOW_HEIGHT = 560
RESULTS_HEIGHT = 390
RESULT_TILE_SCROLL_STEP = 82
VISIBLE_RESULT_COUNT = 4


def run_app(config: LauncherConfig | None = None) -> None:
    """
    Flet アプリケーションとしてランチャーを起動する。
    """
    import flet as ft

    app_config = config or LauncherConfig.from_env()
    client = LauncherApiClient(
        app_config.api_base_url,
        gantt_api_base_url=app_config.gantt_api_base_url,
        timeout=app_config.request_timeout,
    )
    ft.app(target=lambda page: LauncherApp(page, client, app_config).build())


class LauncherApp:
    """
    Flet のページ状態と検索・選択・起動操作をまとめる。
    """

    def __init__(self, page: Any, client: LauncherApiClient, config: LauncherConfig) -> None:
        self.page = page
        self.client = client
        self.config = config
        self.results: list[SearchResultItem] = []
        self.selected_index = 0
        self.search_timer: threading.Timer | None = None
        self.hotkeys: GlobalHotkeyController | None = None
        self.is_hidden = False
        self.search_sequence = 0
        self._show_time: float = 0.0
        self._last_open_request_time: float = 0.0
        self._last_open_request_key = ""
        self.include_gantt_tasks = False
        self.active_screen = "search"
        self.gantt_parent = config.gantt_parent
        self._suppress_render_focus = False

    def build(self) -> None:
        """
        ページの外観・イベント・主要コントロールを初期化する。
        """
        import flet as ft

        self.ft = ft
        self.page.title = "Local Fulltext Search Launcher"
        self.page.bgcolor = "#0f172a"
        self.page.padding = 0
        self._configure_window()
        self.query = ft.TextField(
            autofocus=True,
            border=ft.InputBorder.NONE,
            hint_text="検索語を入力",
            text_style=ft.TextStyle(size=26, color="#e5eefc", font_family="Inter"),
            hint_style=ft.TextStyle(size=26, color="#64748b", font_family="Inter"),
            cursor_color="#60a5fa",
            on_change=self._on_query_change,
            on_submit=lambda event: self._open_selected(),
        )
        self.status = ft.Text("", color="#94a3b8", size=12)
        self.memo_status = ft.Text("", color="#94a3b8", size=12)
        self.results_list = ft.ListView(spacing=8, height=RESULTS_HEIGHT, padding=ft.padding.only(right=4), auto_scroll=False)
        self.results_column = self.results_list
        self.clear_button = ft.IconButton(
            icon=ft.Icons.CLOSE_ROUNDED,
            icon_color="#94a3b8",
            tooltip="検索をクリア",
            width=40,
            height=40,
            on_click=lambda event: self._clear_search(),
        )
        self.gui_button = ft.TextButton(
            "Web GUI",
            icon=ft.Icons.OPEN_IN_BROWSER_ROUNDED,
            style=ft.ButtonStyle(color="#93c5fd", padding=ft.padding.symmetric(horizontal=10, vertical=6)),
            on_click=lambda event: self._open_gui_url(),
        )
        self.gantt_toggle = ft.Checkbox(
            label="gantt",
            value=False,
            check_color="#0f172a",
            fill_color="#60a5fa",
            label_style=ft.TextStyle(color="#bfdbfe", size=12),
            on_change=self._on_gantt_toggle_change,
        )
        self.memo_field = ft.TextField(
            border=ft.InputBorder.NONE,
            hint_text="タスク名\nメモ",
            multiline=True,
            min_lines=10,
            max_lines=10,
            text_style=ft.TextStyle(size=18, color="#e5eefc", font_family="Inter"),
            hint_style=ft.TextStyle(size=16, color="#64748b", font_family="Inter"),
            cursor_color="#60a5fa",
        )
        self.memo_parent_label = ft.Text(f"parent: {self.gantt_parent}", color="#bfdbfe", size=12)
        self.search_area = ft.Column(
            spacing=12,
            visible=True,
            controls=[
                ft.Row(
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Icon(ft.Icons.SEARCH_ROUNDED, color="#60a5fa", size=30),
                        ft.Container(expand=True, content=self.query),
                        self.gantt_toggle,
                        self.clear_button,
                        self.gui_button,
                    ],
                ),
                ft.Container(
                    height=RESULTS_HEIGHT,
                    clip_behavior=ft.ClipBehavior.HARD_EDGE,
                    content=self.results_list,
                ),
                self.status,
            ],
        )
        self.memo_area = ft.Column(
            spacing=12,
            visible=False,
            controls=[
                ft.Row(
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    controls=[
                        ft.Text("gantt メモ", color="#e5eefc", size=18, weight=ft.FontWeight.W_600),
                        ft.Container(expand=True),
                        self.memo_parent_label,
                    ],
                ),
                ft.Container(
                    height=RESULTS_HEIGHT,
                    padding=ft.padding.symmetric(horizontal=14, vertical=12),
                    border_radius=8,
                    bgcolor="#111827",
                    border=ft.border.all(1, "#1f2937"),
                    content=self.memo_field,
                ),
                self.memo_status,
            ],
        )
        self.root = ft.Container(
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            padding=ft.padding.symmetric(horizontal=22, vertical=18),
            border_radius=18,
            bgcolor="#0f172a",
            border=ft.border.all(1, "#1d4ed8"),
            shadow=ft.BoxShadow(blur_radius=34, color="#000000", offset=ft.Offset(0, 18)),
            content=ft.Column(
                spacing=12,
                controls=[
                    ft.WindowDragArea(
                        content=ft.Container(
                            height=18,
                            alignment=ft.Alignment(0, 0),
                            content=ft.Container(width=86, height=4, border_radius=2, bgcolor="#334155"),
                        )
                    ),
                    self.search_area,
                    self.memo_area,
                ],
            ),
        )
        self.page.add(self.root)
        self.page.on_keyboard_event = self._on_keyboard
        self.page.on_window_event = self._on_window_event
        self.hotkeys = GlobalHotkeyController(
            self.toggle_window,
            on_enter=self._open_selected_from_global_enter,
            enter_enabled=self._global_enter_enabled,
        )
        if self.hotkeys.start():
            self.status.value = f"Hotkey: {hotkey_spec_for_platform()}"
        else:
            self.status.value = "pynput が未導入のため、ウィンドウ表示中のキー操作のみ有効です。"
        self.page.update()

    def toggle_window(self) -> None:
        """
        ホットキーから呼ばれ、ウィンドウの表示状態を切り替える。
        pynput のリスナースレッドから呼ばれるため、page.run_task で
        メインスレッドへディスパッチする。
        """

        async def _toggle() -> None:
            if self.is_hidden or bool(getattr(self.page.window, "minimized", False)):
                self._show_window()
            else:
                self._hide_window()

        self.page.run_task(_toggle)

    def _show_window(self) -> None:
        """
        セッションを閉じずに、最小化していたランチャーを前面へ戻す。
        """
        self.is_hidden = False
        self._show_time = time.monotonic()
        self.page.window.minimized = False
        self.page.window.opacity = 1
        self._run_window_task(self._restore_window_and_query_focus)
        self.page.update()

    async def _restore_window_and_query_focus(self) -> None:
        """
        Windows で再表示後の Enter 起動が失われないよう、前面化後に検索欄へフォーカスする。
        """
        await self.page.window.center()
        await self.page.window.to_front()
        await self.query.focus()

    def _hide_window(self) -> None:
        """
        Flet セッションを維持したままランチャーを隠す。
        """
        self.is_hidden = True
        self.page.window.minimized = True
        self.page.update()

    def _configure_window(self) -> None:
        """
        Spotlight 風のフレームレス常時手前ウィンドウに設定する。
        """
        window = self.page.window
        window.width = WINDOW_WIDTH
        window.height = WINDOW_HEIGHT
        window.frameless = True
        window.transparent = False
        window.bgcolor = "#0f172a"
        window.always_on_top = True
        window.resizable = False
        window.skip_task_bar = True
        self._run_window_task(window.center)

    def _run_window_task(self, task: object) -> None:
        """
        Flet 0.84 以降の非同期ウィンドウ操作を同期 UI イベントから起動する。
        """
        if callable(task):
            future = self.page.run_task(task)
            add_done_callback = getattr(future, "add_done_callback", None)
            if callable(add_done_callback):
                add_done_callback(_log_task_error)

    def _on_query_change(self, event: Any) -> None:
        """
        入力変更を短くデバウンスしてバックエンド検索を実行する。
        """
        if self.search_timer is not None:
            self.search_timer.cancel()
        query = str(event.control.value or "").strip()
        self.search_sequence += 1
        sequence = self.search_sequence
        if not query:
            self.results = []
            self.selected_index = 0
            self.status.value = ""
            self._render_results()
            return
        self.status.value = "検索中..."
        self.page.update()
        self.search_timer = threading.Timer(0.18, lambda: self._search(query, sequence))
        self.search_timer.daemon = True
        self.search_timer.start()

    def _clear_search(self) -> None:
        """
        検索語・結果・選択状態を初期化して入力欄へフォーカスを戻す。
        """
        if self.search_timer is not None:
            self.search_timer.cancel()
            self.search_timer = None
        self.search_sequence += 1
        self.query.value = ""
        self.results = []
        self.selected_index = 0
        self.status.value = ""
        self._render_results()
        self._focus_query()

    def _search(self, query: str, sequence: int) -> None:
        """
        バックグラウンドで API 検索を実行し、UI 更新はメインスレッドへ戻す。
        """
        try:
            response = self.client.search(query, limit=self.config.search_limit, include_gantt_tasks=self.include_gantt_tasks)
        except Exception as error:
            logger.exception("Launcher search failed: query=%r api_base_url=%s", query, self.config.api_base_url)
            if sequence != self.search_sequence:
                return
            message = str(error)

            async def _apply_error() -> None:
                self.results = []
                self.status.value = f"検索に失敗しました: {message}"
                self._render_results()

            self.page.run_task(_apply_error)
        else:
            if sequence != self.search_sequence:
                return
            items = response.items
            total = response.total
            has_more = response.has_more

            async def _apply_results() -> None:
                self.results = items
                self.selected_index = 0
                suffix = " さらに結果があります" if has_more else ""
                self.status.value = f"{total} 件{suffix}"
                self._render_results()

            self.page.run_task(_apply_results)

    def _render_results(self) -> None:
        """
        現在の検索結果と選択状態を Flet コントロールへ反映する。
        """
        controls = []
        for index, item in enumerate(self.results):
            controls.append(self._result_tile(item, index=index, selected=index == self.selected_index))
        self.results_column.controls = controls
        self.page.update()
        if self.active_screen == "search" and not self.is_hidden and not self._suppress_render_focus:
            self._focus_query()

    def _result_tile(self, item: SearchResultItem, *, index: int, selected: bool) -> Any:
        """
        検索結果 1 件を選択可能なタイルとして描画する。
        """
        ft = self.ft
        snippet = strip_html(item.snippet)
        reveal_label = "Explorerで開く" if self._platform_name() == "Windows" else "Finderで開く"
        action_controls = []
        if item.source_type == "gantt":
            if item.gantt_link:
                action_controls.append(self._small_action_button("ganttのリンクを開く", ft.Icons.OPEN_IN_NEW_ROUNDED, lambda event, result=item: self._open_gantt_link(result)))
        else:
            action_controls = [
                self._small_action_button("フルパス", ft.Icons.CONTENT_COPY_ROUNDED, lambda event, result=item: self._copy_path(result)),
                self._small_action_button(reveal_label, ft.Icons.FOLDER_OPEN_ROUNDED, lambda event, result=item: self._reveal_item(result)),
                self._small_action_button("フォルダを開く", ft.Icons.OPEN_IN_NEW_ROUNDED, lambda event, result=item: self._open_folder_url(result)),
            ]
        return ft.Container(
            key=f"result-{index}",
            on_click=lambda event, result=item: self._select_and_open(result),
            padding=ft.padding.symmetric(horizontal=14, vertical=9),
            border_radius=8,
            bgcolor="#1d4ed8" if selected else "#111827",
            border=ft.border.all(1, "#60a5fa" if selected else "#1f2937"),
            animate=ft.Animation(120, ft.AnimationCurve.EASE_OUT),
            content=ft.Row(
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                controls=[
                    ft.Icon(self._icon_for_item(item), color="#bfdbfe" if selected else "#94a3b8", size=22),
                    ft.Column(
                        expand=True,
                        spacing=2,
                        controls=[
                            ft.Text(item.file_name, color="#f8fafc", size=15, weight=ft.FontWeight.W_600, max_lines=1),
                            ft.Text(item.full_path, color="#93c5fd" if selected else "#94a3b8", size=11, max_lines=1),
                            ft.Text(snippet, color="#cbd5e1", size=12, max_lines=1),
                        ],
                    ),
                    ft.Row(
                        spacing=6,
                        controls=action_controls,
                    ),
                ],
            ),
        )

    def _small_action_button(self, label: str, icon: Any, handler: Any) -> Any:
        """
        検索結果カード内の小さな操作ボタンを作る。
        """
        ft = self.ft
        return ft.TextButton(
            label,
            icon=icon,
            style=ft.ButtonStyle(
                color="#dbeafe",
                bgcolor="#1e293b",
                padding=ft.padding.symmetric(horizontal=8, vertical=5),
                shape=ft.RoundedRectangleBorder(radius=6),
            ),
            on_click=handler,
        )

    def _on_keyboard(self, event: Any) -> None:
        """
        矢印・Enter・Escape のランチャー操作を処理する。
        """
        key = _normalize_flet_key_name(getattr(event, "key", ""))
        if key == "Escape":
            self._hide_window()
        elif key == "Tab":
            self._switch_screen("memo" if self.active_screen == "search" else "search")
        elif key == "Arrow Down":
            self._move_selection(1)
        elif key == "Arrow Up":
            self._move_selection(-1)
        elif key == "Enter":
            if self.active_screen == "memo":
                if getattr(event, "meta", False) or getattr(event, "shift", False):
                    self._append_memo_newline()
                else:
                    self._submit_memo()
                return
            if getattr(event, "meta", False) or getattr(event, "ctrl", False):
                self._reveal_selected()
            else:
                self._open_selected()

    def _switch_screen(self, screen: str) -> None:
        """
        Tab キーで検索画面と gantt メモ画面を切り替える。
        """
        self.active_screen = "memo" if screen == "memo" else "search"
        self.search_area.visible = self.active_screen == "search"
        self.memo_area.visible = self.active_screen == "memo"
        if self.active_screen == "memo":
            self._run_window_task(self.memo_field.focus)
        else:
            self._focus_query()
        self.page.update()

    def _append_memo_newline(self) -> None:
        """
        メモ画面で Cmd+Return / Shift+Return を改行として扱う。
        """
        self.memo_field.value = f"{self.memo_field.value or ''}\n"
        self.page.update()

    def _submit_memo(self) -> None:
        """
        メモ入力を gantt タスクに変換して作成 API へ送信する。
        """
        raw_text = str(self.memo_field.value or "")
        if not raw_text.strip():
            self.memo_status.value = "タスク名を入力してください"
            self.page.update()
            return
        parent = self._load_gantt_parent()
        payload = build_gantt_task_payload(raw_text, parent=parent)
        if not str(payload["text"]).strip():
            self.memo_status.value = "1行目にタスク名を入力してください"
            self.page.update()
            return
        try:
            self.client.create_gantt_task(payload)
        except Exception as error:
            self.memo_status.value = f"gantt 追加に失敗しました: {error}"
        else:
            self.memo_field.value = ""
            self.memo_status.value = "gantt に追加しました"
        self.page.update()

    def _load_gantt_parent(self) -> int:
        """
        Web の設定ドロワーで保存した gantt parent ID を取得する。
        """
        try:
            settings = self.client.get_app_settings()
        except Exception:
            return self.gantt_parent
        self.gantt_parent = normalize_parent_id(settings.get("gantt_parent"), default=self.gantt_parent)
        self.memo_parent_label.value = f"parent: {self.gantt_parent}"
        return self.gantt_parent

    _BLUR_GUARD_SECONDS = 0.3

    def _on_window_event(self, event: Any) -> None:
        """
        フォーカス喪失時に自動でランチャーを隠す。
        表示直後の blur はウィンドウマネージャー起因のため無視する。
        """
        if getattr(event, "data", "") == "blur":
            if time.monotonic() - self._show_time < self._BLUR_GUARD_SECONDS:
                return
            self._hide_window()

    def _move_selection(self, delta: int) -> None:
        """
        検索結果の選択位置を上下に移動する。
        """
        if not self.results:
            return
        self.selected_index = (self.selected_index + delta) % len(self.results)
        self._suppress_render_focus = True
        try:
            self._render_results()
        finally:
            self._suppress_render_focus = False
        self._scroll_to_selected(delta)
        self._focus_query()

    def _scroll_to_selected(self, delta: int = 0) -> None:
        """
        キーボード選択中のカードがリスト表示範囲に入るようスクロールする。
        """
        scroll_to = getattr(self.results_column, "scroll_to", None)
        if callable(scroll_to):
            if delta > 0:
                anchor_index = max(self.selected_index - VISIBLE_RESULT_COUNT + 1, 0)
            else:
                anchor_index = self.selected_index
            offset = max(anchor_index * RESULT_TILE_SCROLL_STEP, 0)
            result = scroll_to(offset=offset, duration=120)
            if inspect.isawaitable(result):
                async def _await_scroll() -> None:
                    await result
                self.page.run_task(_await_scroll)
            self.page.update()

    def _open_selected(self) -> None:
        """
        選択中の結果を Web アプリ互換 URL で開き、アクセス数を記録する。
        """
        if not self.results:
            return
        self._select_and_open(self.results[self.selected_index])

    def _global_enter_enabled(self) -> bool:
        """
        Flet の Enter イベントが失われた場合だけ、検索画面表示中の単独 Enter を補助する。
        """
        return self.active_screen == "search" and not self.is_hidden

    def _open_selected_from_global_enter(self) -> None:
        """
        pynput のリスナースレッドから Enter 起動を UI スレッドへ戻す。
        """

        async def _open() -> None:
            self._open_selected()

        future = self.page.run_task(_open)
        add_done_callback = getattr(future, "add_done_callback", None)
        if callable(add_done_callback):
            add_done_callback(_log_task_error)

    def _select_and_open(self, item: SearchResultItem) -> None:
        """
        指定結果を開いた後、ランチャーを自動で隠す。
        """
        try:
            if item.source_type == "gantt":
                if self._is_duplicate_open_request(f"gantt:{abs(item.file_id)}"):
                    return
                self.client.open_gantt_task_input(abs(item.file_id))
                self._hide_window()
                self.page.update()
                return
            open_url = primary_web_url_for_item(item, self.config.web_base_url)
            if self._is_duplicate_open_request(open_url):
                return
            webbrowser.open(open_url)
            if item.result_kind == "file" and item.source_type != "gantt" and item.file_id > 0:
                self.client.record_click(item.file_id)
            self._hide_window()
        except (OSError, LauncherApiError) as error:
            self.status.value = f"ファイルを開けませんでした: {error}"
        self.page.update()

    def _open_gantt_link(self, item: SearchResultItem) -> None:
        """
        gantt タスクに設定されているリンクを既定ブラウザで開く。
        """
        if item.gantt_link:
            webbrowser.open(item.gantt_link)

    def _reveal_selected(self) -> None:
        """
        選択中の結果の保存場所を開く。
        """
        if not self.results:
            return
        item = self.results[self.selected_index]
        self._reveal_item(item)

    def _reveal_item(self, item: SearchResultItem) -> None:
        """
        指定結果の保存場所を Explorer / Finder で開く。
        """
        if item.source_type == "gantt":
            self._select_and_open(item)
            return
        target_path = item.full_path if item.result_kind == "folder" else folder_path_for_item(item)
        try:
            self.client.open_location(target_path)
            self._hide_window()
        except LauncherApiError as error:
            self.status.value = f"保存場所を開けませんでした: {error}"
        self.page.update()

    def _is_duplicate_open_request(self, request_key: str) -> bool:
        """
        Enter の submit/key イベント重複で同じ結果を複数回開かないようにする。
        """
        current_time = time.monotonic()
        if request_key == self._last_open_request_key and current_time - self._last_open_request_time < 1.0:
            return True
        self._last_open_request_key = request_key
        self._last_open_request_time = current_time
        return False

    def _copy_path(self, item: SearchResultItem) -> None:
        """
        フルパスをクリップボードへコピーする。
        """
        self._copy_text_to_clipboard(item.full_path)
        self.status.value = "クリップボードにコピーしました"
        self.page.update()

    def _copy_text_to_clipboard(self, text: str) -> None:
        """
        Flet の非同期 clipboard API と Windows の OS クリップボードへ文字列をコピーする。
        """
        set_clipboard = getattr(self.page, "set_clipboard", None)
        if callable(set_clipboard):
            set_clipboard(text)
        else:
            clipboard = getattr(self.page, "clipboard", None)
            clipboard_set = getattr(clipboard, "set", None)
            if callable(clipboard_set):
                result = clipboard_set(text)
                if inspect.isawaitable(result):
                    async def _await_clipboard_set() -> None:
                        await result

                    self.page.run_task(_await_clipboard_set)

        if platform.system() == "Windows":
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", "$input | Set-Clipboard"],
                input=text,
                text=True,
                check=False,
                capture_output=True,
            )

    def _open_folder_url(self, item: SearchResultItem) -> None:
        """
        Web アプリのフォルダリンクを既定ブラウザで開く。
        """
        webbrowser.open(folder_web_url_for_item(item, self.config.web_base_url))

    def _open_gui_url(self) -> None:
        """
        Web GUI を既定ブラウザで開く。
        """
        webbrowser.open("http://127.0.0.1:8079/")
        self._hide_window()

    def _on_gantt_toggle_change(self, event: Any) -> None:
        """
        ランチャーから gantt タスク検索へ切り替え、現在の検索語で再検索する。
        """
        self.include_gantt_tasks = bool(getattr(event.control, "value", False))
        query = str(self.query.value or "").strip()
        if not query:
            return
        if self.search_timer is not None:
            self.search_timer.cancel()
        self.search_sequence += 1
        sequence = self.search_sequence
        self.status.value = "検索中..."
        self.page.update()
        self.search_timer = threading.Timer(0.18, lambda: self._search(query, sequence))
        self.search_timer.daemon = True
        self.search_timer.start()

    def _focus_query(self) -> None:
        """
        Windows の Flet で結果側へ移ったフォーカスを検索欄へ戻し、Enter 起動を安定させる。
        """
        query = getattr(self, "query", None)
        focus = getattr(query, "focus", None)
        if callable(focus):
            self._run_window_task(focus)

    @staticmethod
    def _platform_name() -> str:
        """
        OS 名を返す。テスト時に差し替えやすいよう分離する。
        """
        import platform

        return platform.system()



    @staticmethod
    def _icon_for_item(item: SearchResultItem) -> Any:
        """
        結果種別に合う Flet アイコンを返す。
        """
        import flet as ft

        if item.result_kind == "folder":
            return ft.Icons.FOLDER_ROUNDED
        return ft.Icons.DESCRIPTION_ROUNDED


def _log_task_error(future: Any) -> None:
    """
    非同期ウィンドウ操作の例外でランチャー全体が落ちないようログに閉じ込める。
    """
    try:
        future.result()
    except Exception:
        logger.exception("Flet window task failed.")


def _normalize_flet_key_name(key: object) -> str:
    """
    Flet のバージョンや Windows の入力経路で揺れるキー名をランチャー内部表現へ揃える。
    """
    normalized = str(key or "").strip().lower().replace("_", " ").replace("-", " ")
    normalized = " ".join(normalized.split())
    if normalized in {"escape", "esc"}:
        return "Escape"
    if normalized in {"arrow down", "arrowdown", "down"}:
        return "Arrow Down"
    if normalized in {"arrow up", "arrowup", "up"}:
        return "Arrow Up"
    if normalized in {"enter", "return", "numpad enter", "numpadenter"}:
        return "Enter"
    if normalized in {"tab"}:
        return "Tab"
    return str(key or "")
