"""
macOS Spaces 上でも現在のデスクトップへ表示できる Cocoa ネイティブランチャーを提供する。
"""

from __future__ import annotations

import html
import os
import platform
import re
import threading
from typing import Any
from urllib.parse import quote
import webbrowser

import AppKit
import objc
from PyObjCTools import AppHelper

from launcher_app.api.client import LauncherApiClient
from launcher_app.config import LauncherConfig
from launcher_app.models import SearchResultItem
from launcher_app.services.hotkeys import hotkey_spec_for_platform


PANEL_WIDTH = 780
PANEL_HEIGHT = 520
WEB_OPEN_BASE_URL = "http://localhost:8001"
_delegate_ref: Any | None = None


class LauncherPanel(AppKit.NSPanel):
    """
    ボーダーレスでも検索フィールドへキー入力できるランチャー用パネル。
    """

    def canBecomeKeyWindow(self) -> bool:
        """
        NSSearchField が入力フォーカスを受け取れるようにする。
        """
        return True

    def canBecomeMainWindow(self) -> bool:
        """
        アプリを前面化したときにメインウィンドウとして扱えるようにする。
        """
        return True


class LauncherDelegate(AppKit.NSObject):
    """
    Cocoa パネルの入力・検索・ホットキー処理をまとめる。
    """

    def initWithClient_config_(self, client: LauncherApiClient, config: LauncherConfig) -> "LauncherDelegate":
        self = objc.super(LauncherDelegate, self).init()
        if self is None:
            return self
        self.client = client
        self.config = config
        self.results: list[SearchResultItem] = []
        self.selected_index = 0
        self.search_sequence = 0
        self.search_timer: threading.Timer | None = None
        self.hotkey_monitors: list[Any] = []
        self.hotkey_activated = False
        self.panel = None
        self.search_field = None
        self.status_label = None
        self.results_stack = None
        self.result_lookup: dict[int, SearchResultItem] = {}
        return self

    def applicationDidFinishLaunching_(self, notification: Any) -> None:
        """
        アプリ起動時に Spaces 対応パネルを構築し、ホットキー監視を開始する。
        """
        if self.panel is not None:
            return
        self._build_panel()
        self._start_hotkey_monitor()
        self.status_label.setStringValue_(f"Hotkey: {hotkey_spec_for_platform()}")
        self.show_panel()

    def controlTextDidChange_(self, notification: Any) -> None:
        """
        検索語の変更をデバウンスしてバックエンド検索を実行する。
        """
        if self.search_timer is not None:
            self.search_timer.cancel()
        query = str(self.search_field.stringValue()).strip()
        self.search_sequence += 1
        sequence = self.search_sequence
        if not query:
            self.results = []
            self.status_label.setStringValue_(f"Hotkey: {hotkey_spec_for_platform()}")
            self._render_results()
            return
        self.status_label.setStringValue_("検索中...")
        self.search_timer = threading.Timer(0.18, lambda: self._search(query, sequence))
        self.search_timer.daemon = True
        self.search_timer.start()

    def toggle_panel(self) -> None:
        """
        パネルの表示・非表示を切り替える。
        """
        if self.panel.isVisible():
            self.hide_panel()
        else:
            self.show_panel()

    @objc.python_method
    def _start_hotkey_monitor(self) -> None:
        """
        Cocoa の modifier flags 監視で Option + Command を検出する。
        """
        mask = AppKit.NSEventMaskFlagsChanged

        def handler(event: Any) -> Any:
            self._handle_modifier_event(event)
            return event

        global_monitor = AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(mask, handler)
        local_monitor = AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(mask, handler)
        self.hotkey_monitors = [monitor for monitor in (global_monitor, local_monitor) if monitor is not None]

    @objc.python_method
    def _handle_modifier_event(self, event: Any) -> None:
        """
        Option + Command が揃った瞬間にだけ表示状態を切り替える。
        """
        flags = event.modifierFlags()
        required = AppKit.NSEventModifierFlagCommand | AppKit.NSEventModifierFlagOption
        active = (flags & required) == required
        if active and not self.hotkey_activated:
            self.hotkey_activated = True
            self.toggle_panel()
        elif not active:
            self.hotkey_activated = False

    @objc.python_method
    def show_panel(self) -> None:
        """
        現在の仮想デスクトップ上にパネルを表示する。
        """
        self._center_panel_on_mouse_screen()
        self.panel.setAlphaValue_(1.0)
        AppKit.NSApp.activateIgnoringOtherApps_(True)
        self.panel.makeKeyWindow()
        self.panel.makeKeyAndOrderFront_(None)
        self.search_field.becomeFirstResponder()

    @objc.python_method
    def hide_panel(self) -> None:
        """
        セッションを維持したままパネルを閉じる。
        """
        self.panel.orderOut_(None)

    @objc.python_method
    def _build_panel(self) -> None:
        """
        Glassmorphism 風の検索パネルと結果リストを構築する。
        """
        style = (
            AppKit.NSWindowStyleMaskBorderless
            | AppKit.NSWindowStyleMaskFullSizeContentView
        )
        self.panel = LauncherPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            AppKit.NSMakeRect(0, 0, PANEL_WIDTH, PANEL_HEIGHT),
            style,
            AppKit.NSBackingStoreBuffered,
            False,
        )
        self.panel.setLevel_(AppKit.NSFloatingWindowLevel)
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setCollectionBehavior_(
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
            | AppKit.NSWindowCollectionBehaviorStationary
        )

        content = AppKit.NSView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, PANEL_WIDTH, PANEL_HEIGHT))
        content.setWantsLayer_(True)
        content.layer().setCornerRadius_(24)
        content.layer().setBackgroundColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.06, 0.09, 0.16, 0.96).CGColor())
        content.layer().setBorderColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.22, 0.48, 1.0, 0.9).CGColor())
        content.layer().setBorderWidth_(1.0)
        self.panel.setContentView_(content)

        self.search_field = AppKit.NSSearchField.alloc().initWithFrame_(AppKit.NSMakeRect(34, PANEL_HEIGHT - 86, PANEL_WIDTH - 68, 48))
        self.search_field.setDelegate_(self)
        self.search_field.setPlaceholderString_("検索語を入力")
        self.search_field.setFont_(AppKit.NSFont.systemFontOfSize_weight_(28, AppKit.NSFontWeightRegular))
        self.search_field.setTextColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.9, 0.94, 1.0, 1.0))
        self.search_field.setDrawsBackground_(False)
        content.addSubview_(self.search_field)

        scroll = AppKit.NSScrollView.alloc().initWithFrame_(AppKit.NSMakeRect(24, 54, PANEL_WIDTH - 48, PANEL_HEIGHT - 158))
        scroll.setDrawsBackground_(False)
        scroll.setBorderType_(AppKit.NSNoBorder)
        scroll.setHasVerticalScroller_(True)
        self.results_stack = AppKit.NSStackView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, PANEL_WIDTH - 66, PANEL_HEIGHT - 158))
        self.results_stack.setOrientation_(AppKit.NSUserInterfaceLayoutOrientationVertical)
        self.results_stack.setSpacing_(8)
        self.results_stack.setAlignment_(AppKit.NSLayoutAttributeLeading)
        scroll.setDocumentView_(self.results_stack)
        content.addSubview_(scroll)

        self.status_label = AppKit.NSTextField.labelWithString_(f"Hotkey: {hotkey_spec_for_platform()}")
        self.status_label.setFrame_(AppKit.NSMakeRect(34, 22, PANEL_WIDTH - 68, 20))
        self.status_label.setTextColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.58, 0.64, 0.73, 1.0))
        self.status_label.setFont_(AppKit.NSFont.boldSystemFontOfSize_(13))
        content.addSubview_(self.status_label)

    @objc.python_method
    def _center_panel_on_mouse_screen(self) -> None:
        """
        マウスカーソルがある画面の中央上寄りへパネルを移動する。
        """
        mouse = AppKit.NSEvent.mouseLocation()
        target_screen = AppKit.NSScreen.mainScreen()
        for screen in AppKit.NSScreen.screens():
            if AppKit.NSPointInRect(mouse, screen.frame()):
                target_screen = screen
                break
        frame = target_screen.visibleFrame()
        x = frame.origin.x + (frame.size.width - PANEL_WIDTH) / 2
        y = frame.origin.y + frame.size.height - PANEL_HEIGHT - 120
        self.panel.setFrame_display_(AppKit.NSMakeRect(x, y, PANEL_WIDTH, PANEL_HEIGHT), True)

    @objc.python_method
    def _search(self, query: str, sequence: int) -> None:
        """
        バックグラウンド検索を実行し、結果更新はメインスレッドへ戻す。
        """
        try:
            response = self.client.search(query, limit=self.config.search_limit)
        except Exception as error:
            AppHelper.callAfter(self._show_search_error, sequence, str(error))
        else:
            AppHelper.callAfter(self._show_search_results, sequence, response.total, response.items)

    @objc.python_method
    def _show_search_error(self, sequence: int, message: str) -> None:
        """
        最新検索のエラーだけをステータスへ表示する。
        """
        if sequence != self.search_sequence:
            return
        self.results = []
        self.status_label.setStringValue_(f"検索に失敗しました: {message}")
        self._render_results()

    @objc.python_method
    def _show_search_results(self, sequence: int, total: int, items: list[SearchResultItem]) -> None:
        """
        最新検索の結果だけを結果リストへ反映する。
        """
        if sequence != self.search_sequence:
            return
        self.results = items
        self.selected_index = 0
        self.status_label.setStringValue_(f"{total} 件")
        self._render_results()

    @objc.python_method
    def _render_results(self) -> None:
        """
        現在の検索結果をクリック可能なカードとして描画する。
        """
        for view in list(self.results_stack.arrangedSubviews()):
            self.results_stack.removeArrangedSubview_(view)
            view.removeFromSuperview()
        self.result_lookup = {item.file_id: item for item in self.results}
        for index, item in enumerate(self.results):
            self.results_stack.addArrangedSubview_(self._make_result_card(item, index == self.selected_index))

    @objc.python_method
    def _make_result_card(self, item: SearchResultItem, selected: bool) -> AppKit.NSView:
        """
        検索結果 1 件を Web アプリの結果カードに近い操作群として描画する。
        """
        card = AppKit.NSView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, PANEL_WIDTH - 74, 116))
        card.setWantsLayer_(True)
        color = (0.10, 0.32, 0.86, 0.98) if selected else (0.07, 0.11, 0.18, 0.98)
        card.layer().setBackgroundColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(*color).CGColor())
        card.layer().setCornerRadius_(12)

        title = f"{item.file_name}\n{item.full_path}\n{_strip_html(item.snippet)[:112]}"
        button = AppKit.NSButton.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, PANEL_WIDTH - 74, 96))
        button.setTitle_(title)
        button.setBezelStyle_(AppKit.NSBezelStyleRegularSquare)
        button.setBordered_(False)
        button.setAlignment_(AppKit.NSTextAlignmentLeft)
        button.setFont_(AppKit.NSFont.systemFontOfSize_weight_(14, AppKit.NSFontWeightSemibold))
        button.setContentTintColor_(AppKit.NSColor.whiteColor())
        button.setTarget_(self)
        button.setAction_("openResult:")
        button.setTag_(int(item.file_id))
        card.addSubview_(button)

        finder_button = AppKit.NSButton.buttonWithTitle_target_action_("Finderで開く", self, "revealResult:")
        finder_button.setFrame_(AppKit.NSMakeRect(PANEL_WIDTH - 218, 8, 100, 26))
        finder_button.setTag_(int(item.file_id))
        card.addSubview_(finder_button)

        folder_button = AppKit.NSButton.buttonWithTitle_target_action_("フォルダを開く", self, "openFolderResult:")
        folder_button.setFrame_(AppKit.NSMakeRect(PANEL_WIDTH - 112, 8, 104, 26))
        folder_button.setTag_(int(item.file_id))
        card.addSubview_(folder_button)
        return card

    def openResult_(self, sender: Any) -> None:
        """
        Web アプリのタイトルリンクと同じ URL を既定ブラウザで開く。
        """
        file_id = int(sender.tag())
        item = self.result_lookup.get(file_id)
        if item is None:
            return
        try:
            webbrowser.open(primary_web_url_for_item(item))
            if item.result_kind == "file":
                self.client.record_click(item.file_id)
            self.hide_panel()
        except Exception as error:
            self.status_label.setStringValue_(f"ファイルを開けませんでした: {error}")

    def revealResult_(self, sender: Any) -> None:
        """
        Web アプリの Finder で開くボタンと同じ backend API を呼ぶ。
        """
        item = self.result_lookup.get(int(sender.tag()))
        if item is None:
            return
        target_path = item.full_path if item.result_kind == "folder" else folder_path_for_item(item)
        try:
            self.client.open_location(target_path)
        except Exception as error:
            self.status_label.setStringValue_(f"保存場所を開けませんでした: {error}")

    def openFolderResult_(self, sender: Any) -> None:
        """
        Web アプリのフォルダリンクと同じ URL を既定ブラウザで開く。
        """
        item = self.result_lookup.get(int(sender.tag()))
        if item is None:
            return
        webbrowser.open(folder_web_url_for_item(item))


def run_native_mac_app(config: LauncherConfig | None = None) -> None:
    """
    macOS ネイティブパネルとしてランチャーを起動する。
    """
    if platform.system() != "Darwin":
        raise RuntimeError("Native macOS launcher is only available on Darwin.")
    app_config = config or LauncherConfig.from_env()
    client = LauncherApiClient(app_config.api_base_url, timeout=app_config.request_timeout)
    global _delegate_ref
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    delegate = LauncherDelegate.alloc().initWithClient_config_(client, app_config)
    _delegate_ref = delegate
    delegate._build_panel()
    delegate._start_hotkey_monitor()
    delegate.status_label.setStringValue_(f"Hotkey: {hotkey_spec_for_platform()}")
    app.setDelegate_(delegate)
    delegate.show_panel()
    AppHelper.runEventLoop()


def _strip_html(value: str) -> str:
    """
    API スニペットの HTML タグを Cocoa の通常テキストへ変換する。
    """
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def folder_path_for_item(item: SearchResultItem) -> str:
    """
    Web アプリの getFolderPath と同じ用途で、ファイルの親フォルダを返す。
    """
    if item.result_kind == "folder":
        return item.full_path
    folder_path = os.path.dirname(item.full_path)
    return folder_path or item.full_path


def full_path_web_url(path: str) -> str:
    """
    Web アプリの fullPathUrl と同じ URL を生成する。
    """
    return f"{WEB_OPEN_BASE_URL}/api/fullpath?path={quote(path, safe='')}"


def folder_web_url(path: str) -> str:
    """
    Web アプリの folderUrl と同じ URL を生成する。
    """
    return f"{WEB_OPEN_BASE_URL}/?path={quote(path, safe='')}"


def primary_web_url_for_item(item: SearchResultItem) -> str:
    """
    Web アプリの primaryUrl と同じ URL を生成する。
    """
    if item.result_kind == "folder":
        return folder_web_url(item.full_path)
    return full_path_web_url(item.full_path)


def folder_web_url_for_item(item: SearchResultItem) -> str:
    """
    Web アプリのフォルダリンクと同じ URL を生成する。
    """
    return folder_web_url(folder_path_for_item(item))
