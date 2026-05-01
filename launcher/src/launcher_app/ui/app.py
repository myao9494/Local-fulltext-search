"""
Spotlight 風の Flet ランチャー UI を構築する。
"""

from __future__ import annotations

import html
import logging
import re
import threading
from typing import Any

from launcher_app.api.client import LauncherApiClient, LauncherApiError
from launcher_app.config import LauncherConfig
from launcher_app.models import SearchResultItem
from launcher_app.services.file_actions import FileActionError, open_path, reveal_path
from launcher_app.services.hotkeys import GlobalHotkeyController, hotkey_spec_for_platform

logger = logging.getLogger(__name__)


def run_app(config: LauncherConfig | None = None) -> None:
    """
    Flet アプリケーションとしてランチャーを起動する。
    """
    import flet as ft

    app_config = config or LauncherConfig.from_env()
    client = LauncherApiClient(
        app_config.api_base_url,
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

    def build(self) -> None:
        """
        ページの外観・イベント・主要コントロールを初期化する。
        """
        import flet as ft

        self.ft = ft
        self.page.title = "Local Fulltext Search Launcher"
        self.page.bgcolor = ft.Colors.TRANSPARENT
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
        self.results_column = ft.Column(spacing=6)
        self.root = ft.Container(
            width=760,
            padding=ft.padding.symmetric(horizontal=22, vertical=18),
            border_radius=24,
            bgcolor="#0f172a",
            border=ft.border.all(1, "#1d4ed8"),
            shadow=ft.BoxShadow(blur_radius=34, color="#000000", offset=ft.Offset(0, 18)),
            content=ft.Column(
                spacing=14,
                controls=[
                    ft.Row(
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        controls=[
                            ft.Icon(ft.Icons.SEARCH_ROUNDED, color="#60a5fa", size=30),
                            ft.Container(expand=True, content=self.query),
                        ],
                    ),
                    self.results_column,
                    self.status,
                ],
            ),
        )
        self.page.add(ft.Container(alignment=ft.Alignment(0, -1), padding=ft.padding.only(top=120), content=self.root))
        self.page.on_keyboard_event = self._on_keyboard
        self.page.on_window_event = self._on_window_event
        self.hotkeys = GlobalHotkeyController(self.toggle_window)
        if self.hotkeys.start():
            self.status.value = f"Hotkey: {hotkey_spec_for_platform()}"
        else:
            self.status.value = "pynput が未導入のため、ウィンドウ表示中のキー操作のみ有効です。"
        self.page.update()

    def toggle_window(self) -> None:
        """
        ホットキーから呼ばれ、ウィンドウの表示状態を切り替える。
        """
        if self.is_hidden or bool(getattr(self.page.window, "minimized", False)):
            self._show_window()
        else:
            self._hide_window()

    def _show_window(self) -> None:
        """
        セッションを閉じずに、最小化していたランチャーを前面へ戻す。
        """
        self.is_hidden = False
        self.page.window.minimized = False
        self.page.window.opacity = 1
        self._run_window_task(self.page.window.center)
        self._run_window_task(self.page.window.to_front)
        self._run_window_task(self.query.focus)
        self.page.update()

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
        window.width = 820
        window.height = 520
        window.frameless = True
        window.transparent = True
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
            future.add_done_callback(_log_task_error)

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

    def _search(self, query: str, sequence: int) -> None:
        """
        バックグラウンドで検索し、完了後に結果リストを更新する。
        """
        try:
            response = self.client.search(query, limit=self.config.search_limit)
        except Exception as error:
            if sequence != self.search_sequence:
                return
            self.results = []
            self.status.value = f"検索に失敗しました: {error}"
        else:
            if sequence != self.search_sequence:
                return
            self.results = response.items
            self.selected_index = 0
            suffix = " さらに結果があります" if response.has_more else ""
            self.status.value = f"{response.total} 件{suffix}"
        self._render_results()

    def _render_results(self) -> None:
        """
        現在の検索結果と選択状態を Flet コントロールへ反映する。
        """
        controls = []
        for index, item in enumerate(self.results):
            controls.append(self._result_tile(item, selected=index == self.selected_index))
        self.results_column.controls = controls
        self.page.update()

    def _result_tile(self, item: SearchResultItem, *, selected: bool) -> Any:
        """
        検索結果 1 件を選択可能なタイルとして描画する。
        """
        ft = self.ft
        snippet = _strip_html(item.snippet)
        return ft.Container(
            on_click=lambda event, result=item: self._select_and_open(result),
            padding=ft.padding.symmetric(horizontal=14, vertical=10),
            border_radius=12,
            bgcolor="#1d4ed8" if selected else "#111827",
            border=ft.border.all(1, "#60a5fa" if selected else "#1f2937"),
            animate=ft.Animation(120, ft.AnimationCurve.EASE_OUT),
            content=ft.Row(
                spacing=12,
                controls=[
                    ft.Icon(_icon_for_item(item), color="#bfdbfe" if selected else "#94a3b8", size=22),
                    ft.Column(
                        expand=True,
                        spacing=3,
                        controls=[
                            ft.Text(item.file_name, color="#f8fafc", size=15, weight=ft.FontWeight.W_600, max_lines=1),
                            ft.Text(item.full_path, color="#93c5fd" if selected else "#94a3b8", size=11, max_lines=1),
                            ft.Text(snippet, color="#cbd5e1", size=12, max_lines=2),
                        ],
                    ),
                    ft.Text(str(item.click_count), color="#93c5fd", size=12),
                ],
            ),
        )

    def _on_keyboard(self, event: Any) -> None:
        """
        矢印・Enter・Escape のランチャー操作を処理する。
        """
        key = getattr(event, "key", "")
        if key == "Escape":
            self._hide_window()
        elif key == "Arrow Down":
            self._move_selection(1)
        elif key == "Arrow Up":
            self._move_selection(-1)
        elif key == "Enter":
            if getattr(event, "meta", False) or getattr(event, "ctrl", False):
                self._reveal_selected()
            else:
                self._open_selected()

    def _on_window_event(self, event: Any) -> None:
        """
        フォーカス喪失時に自動でランチャーを隠す。
        """
        if getattr(event, "data", "") == "blur":
            self._hide_window()

    def _move_selection(self, delta: int) -> None:
        """
        検索結果の選択位置を上下に移動する。
        """
        if not self.results:
            return
        self.selected_index = (self.selected_index + delta) % len(self.results)
        self._render_results()

    def _open_selected(self) -> None:
        """
        選択中の結果を OS 標準アプリで開き、アクセス数を記録する。
        """
        if not self.results:
            return
        self._select_and_open(self.results[self.selected_index])

    def _select_and_open(self, item: SearchResultItem) -> None:
        """
        指定結果を開いた後、ランチャーを自動で隠す。
        """
        try:
            open_path(item.full_path)
            if item.result_kind == "file":
                self.client.record_click(item.file_id)
            self._hide_window()
        except (FileActionError, LauncherApiError) as error:
            self.status.value = f"ファイルを開けませんでした: {error}"
        self.page.update()

    def _reveal_selected(self) -> None:
        """
        選択中の結果の保存場所を開く。
        """
        if not self.results:
            return
        item = self.results[self.selected_index]
        try:
            reveal_path(item.full_path)
            self._hide_window()
        except FileActionError as error:
            self.status.value = f"保存場所を開けませんでした: {error}"
        self.page.update()


def _strip_html(value: str) -> str:
    """
    API スニペットの mark 等を外し、Flet の通常テキストへ変換する。
    """
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


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
