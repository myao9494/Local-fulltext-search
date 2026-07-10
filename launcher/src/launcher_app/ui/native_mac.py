"""
macOS Spaces 上でも現在のデスクトップへ表示できる Cocoa ネイティブランチャーを提供する。

【仕様】
- gantt メモ画面において、タスク名欄 (memo_title_field) および本文欄 (memo_body_view) での Return/Enter および Shift+Enter キー押下時は、送信を行わずに改行（または通常の入力継続）を行う。
- gantt タスクの送信は、送信ボタンのクリック、または送信ボタンにフォーカス（カーソル）が合っている状態での Return/Enter キー押下時のみ実行する。
"""

from __future__ import annotations

import platform
import threading
import time
from typing import Any
import webbrowser

import AppKit
import objc
try:
    import Quartz
except ImportError:  # pragma: no cover - macOS 以外のテスト環境向け
    Quartz = None
from PyObjCTools import AppHelper

from launcher_app.api.client import LauncherApiClient
from launcher_app.config import LauncherConfig
from launcher_app.gantt_task import build_gantt_task_payload, normalize_parent_id
from launcher_app.models import SearchResultItem
from launcher_app.services.hotkeys import hotkey_spec_for_platform
from launcher_app.ui.urls import (
    folder_path_for_item,
    folder_web_url_for_item,
    full_path_web_url,
    primary_web_url_for_item,
)
from launcher_app.utils import strip_html


PANEL_WIDTH = 780
PANEL_HEIGHT = 520
HOTKEY_WATCHDOG_INTERVAL_SECONDS = 0.08
_delegate_ref: Any | None = None

class FlippedView(AppKit.NSView):
    def isFlipped(self) -> bool:
        return True


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

    def keyDown_(self, event: Any) -> None:
        """
        送信ボタンやキャンセルボタンにフォーカスがある状態で Return キーが押された場合に、アクションを実行する。
        """
        chars = event.characters()
        if chars == "\r" or chars == "\n":
            delegate = self.delegate()
            if delegate is not None:
                first_responder = self.firstResponder()
                if first_responder == delegate.memo_submit_button:
                    delegate._submit_memo()
                    return
                elif first_responder == delegate.memo_cancel_button:
                    delegate._switch_screen("search")
                    return
        objc.super(LauncherPanel, self).keyDown_(event)


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
        self.web_base_url = config.web_base_url
        self.results: list[SearchResultItem] = []
        self.selected_index = 0
        self.search_sequence = 0
        self.search_timer: threading.Timer | None = None
        self.hotkey_monitors: list[Any] = []
        self.hotkey_event_tap = None
        self.hotkey_event_tap_location = None
        self.hotkey_event_tap_source = None
        self.hotkey_event_tap_callback = None
        self.hotkey_watchdog_timer = None
        self.power_notification_center = None
        self.power_notifications_registered = False
        self.activity_token = None
        self.hotkey_activated = False
        self.panel = None
        self.search_field = None
        self.status_label = None
        self.results_stack = None
        self.gui_button = None
        self.gantt_checkbox = None
        self.active_screen = "search"
        self.search_scroll = None
        self.memo_scroll = None
        self.memo_text_view = None
        self.memo_parent_label = None
        self.memo_title_label = None
        self.memo_title_field = None
        self.memo_body_view = None
        self.memo_submit_button = None
        self.memo_cancel_button = None
        self.gantt_parent = config.gantt_parent
        self.include_gantt_tasks = False
        self.last_results_time = 0.0
        return self

    def applicationDidFinishLaunching_(self, notification: Any) -> None:
        """
        アプリ起動時に Spaces 対応パネルを構築し、ホットキー監視を開始する。
        """
        if self.panel is not None:
            return
        self._begin_activity()
        self._build_panel()
        self._start_hotkey_monitor()
        self._start_power_state_monitor()
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
        
        # 検索入力中・通信中はEnterキーを無効化する
        self.last_results_time = float('inf')
        
        if not query:
            self.results = []
            self.status_label.setStringValue_(f"Hotkey: {hotkey_spec_for_platform()}")
            self.last_results_time = time.time()
            self._render_results()
            return
        self.status_label.setStringValue_("検索中...")
        self.search_timer = threading.Timer(0.18, lambda: self._search(query, sequence))
        self.search_timer.daemon = True
        self.search_timer.start()

    def control_textView_doCommandBySelector_(self, control: Any, textView: Any, commandSelector: Any) -> bool:
        """
        NSSearchField および memo_title_field のテキスト入力中の上下キー、Enterキー、ESCキー、Tabキーを捕捉する。
        """
        selector = str(commandSelector)
        if control == self.search_field:
            if selector == "moveUp:":
                self._move_selection(-1)
                return True
            elif selector == "moveDown:":
                self._move_selection(1)
                return True
            elif selector == "insertNewline:":
                self._open_selected()
                return True
            elif selector == "insertTab:":
                self._switch_screen("memo")
                return True
            elif selector == "cancelOperation:":
                self.hide_panel()
                return True
        elif control == self.memo_title_field:
            if selector == "insertTab:":
                self.panel.makeFirstResponder_(self.memo_body_view)
                return True
            elif selector == "insertBacktab:":
                self.panel.makeFirstResponder_(self.memo_cancel_button)
                return True
            elif selector == "insertNewline:":
                # タイトル欄でのEnterでは送信しない。
                # NSTextFieldは単一行のため改行文字を挿入することはできませんが、
                # 送信されずに何もしないように制御します。
                return True
            elif selector == "cancelOperation:":
                self._switch_screen("search")
                return True
        return False

    def textView_doCommandBySelector_(self, textView: Any, commandSelector: Any) -> bool:
        """
        メモ画面のメモ本文入力中の Tab / Shift+Tab / Return / ESC を処理する。
        """
        selector = str(commandSelector)
        if textView == self.memo_body_view:
            if selector == "insertTab:":
                self.panel.makeFirstResponder_(self.memo_submit_button)
                return True
            elif selector == "insertBacktab:":
                self.panel.makeFirstResponder_(self.memo_title_field)
                return True
            elif selector == "insertNewline:":
                # Shift+Enter および通常の Enter でも送信は行わず、常に改行を挿入する
                textView.insertText_("\n")
                return True
            elif selector == "cancelOperation:":
                self._switch_screen("search")
                return True
        return False

    @objc.python_method
    def _move_selection(self, delta: int) -> None:
        """
        検索結果の選択位置を上下に移動し、必要に応じてスクロールする。
        """
        if not self.results:
            return
            
        scroll_view = self.results_stack.enclosingScrollView()
        saved_y = scroll_view.documentVisibleRect().origin.y if scroll_view else 0

        old_index = self.selected_index
        self.selected_index = (self.selected_index + delta) % len(self.results)
        self._update_card_selection(old_index, self.selected_index)
        
        if scroll_view:
            clip_view = scroll_view.contentView()
            clip_view.setBoundsOrigin_(AppKit.NSMakePoint(0, saved_y))
            
        self._scroll_to_selected()

    @objc.python_method
    def _open_selected(self) -> None:
        """
        現在選択中のアイテムを開く。
        """
        if time.time() - getattr(self, "last_results_time", 0.0) < 0.5:
            return
        if not self.results:
            return
        item = self.results[self.selected_index]
        self._open_item(item)

    @objc.python_method
    def _scroll_to_selected(self) -> None:
        if not self.results:
            return
        card_height = 64
        spacing = 8
        y = self.selected_index * (card_height + spacing)
        
        scroll_view = self.results_stack.enclosingScrollView()
        if not scroll_view:
            return
            
        visible_rect = scroll_view.documentVisibleRect()
        current_top = visible_rect.origin.y
        current_bottom = current_top + visible_rect.size.height
        
        top_edge = y
        bottom_edge = y + card_height
        
        new_y = current_top
        
        if top_edge < current_top:
            # 上にはみ出た場合: 対象の上端に合わせる
            new_y = top_edge - spacing
        elif bottom_edge > current_bottom:
            # 下にはみ出た場合: 次のカードが少し見えるように余分にスクロールする
            new_y = bottom_edge - visible_rect.size.height + spacing + (card_height * 0.6)
            
        new_y = max(0, new_y)
        
        # documentViewの最大スクロール位置を超えないようにする
        max_y = max(0, self.results_stack.frame().size.height - visible_rect.size.height)
        new_y = min(new_y, max_y)
        
        clip_view = scroll_view.contentView()
        clip_view.setBoundsOrigin_(AppKit.NSMakePoint(0, new_y))
        scroll_view.reflectScrolledClipView_(clip_view)

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
        セッション全体の入力イベント監視で Command + Option を検出する。
        既に登録済みの場合は二重登録しない。
        """
        if self.hotkey_monitors or self.hotkey_event_tap is not None:
            return
        self._start_hotkey_event_tap()
        self._start_hotkey_watchdog()
        mask = AppKit.NSEventMaskFlagsChanged

        def handler(event: Any) -> Any:
            self._handle_modifier_event(event)
            return event

        global_monitor = AppKit.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(mask, handler)
        local_monitor = AppKit.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(mask, handler)
        self.hotkey_monitors = [monitor for monitor in (global_monitor, local_monitor) if monitor is not None]

    @objc.python_method
    def _start_hotkey_event_tap(self) -> None:
        """
        アプリに依存しにくい CGEventTap で修飾キー変更を監視する。
        """
        if Quartz is None or self.hotkey_event_tap is not None:
            return

        def callback(proxy: Any, event_type: int, event: Any, refcon: Any) -> Any:
            if event_type == Quartz.kCGEventTapDisabledByTimeout:
                Quartz.CGEventTapEnable(self.hotkey_event_tap, True)
                return event
            if event_type == Quartz.kCGEventFlagsChanged:
                self._handle_modifier_flags(Quartz.CGEventGetFlags(event))
            return event

        event_mask = Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged)
        event_tap = None
        event_tap_location = None
        for location in (Quartz.kCGHIDEventTap, Quartz.kCGSessionEventTap):
            event_tap = Quartz.CGEventTapCreate(
                location,
                Quartz.kCGHeadInsertEventTap,
                Quartz.kCGEventTapOptionListenOnly,
                event_mask,
                callback,
                None,
            )
            if event_tap is not None:
                event_tap_location = location
                break
        if event_tap is None:
            return
        source = Quartz.CFMachPortCreateRunLoopSource(None, event_tap, 0)
        Quartz.CFRunLoopAddSource(Quartz.CFRunLoopGetCurrent(), source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(event_tap, True)
        self.hotkey_event_tap = event_tap
        self.hotkey_event_tap_location = event_tap_location
        self.hotkey_event_tap_source = source
        self.hotkey_event_tap_callback = callback

    @objc.python_method
    def _start_hotkey_watchdog(self) -> None:
        """
        event tap の取りこぼしに備え、現在の修飾キー状態を定期確認する。
        """
        if self.hotkey_watchdog_timer is not None:
            return
        timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            HOTKEY_WATCHDOG_INTERVAL_SECONDS,
            self,
            "pollHotkeyState:",
            None,
            True,
        )
        AppKit.NSRunLoop.currentRunLoop().addTimer_forMode_(timer, AppKit.NSRunLoopCommonModes)
        self.hotkey_watchdog_timer = timer

    @objc.python_method
    def _stop_hotkey_watchdog(self) -> None:
        """
        修飾キー状態の定期確認タイマーを停止する。
        """
        if self.hotkey_watchdog_timer is None:
            return
        self.hotkey_watchdog_timer.invalidate()
        self.hotkey_watchdog_timer = None

    def pollHotkeyState_(self, timer: Any) -> None:
        """
        前面アプリがイベントを握る場合でも現在の Command + Option 状態を読む。
        """
        if Quartz is None:
            return
        if self.hotkey_event_tap is not None:
            Quartz.CGEventTapEnable(self.hotkey_event_tap, True)
        flags = Quartz.CGEventSourceFlagsState(Quartz.kCGEventSourceStateCombinedSessionState)
        self._handle_modifier_flags(flags)

    @objc.python_method
    def _stop_hotkey_monitor(self) -> None:
        """
        登録済みの入力イベント監視を解除する。
        """
        self._stop_hotkey_watchdog()
        for monitor in self.hotkey_monitors:
            AppKit.NSEvent.removeMonitor_(monitor)
        self.hotkey_monitors = []
        if Quartz is not None and self.hotkey_event_tap is not None:
            if self.hotkey_event_tap_source is not None:
                Quartz.CFRunLoopRemoveSource(
                    Quartz.CFRunLoopGetCurrent(),
                    self.hotkey_event_tap_source,
                    Quartz.kCFRunLoopCommonModes,
                )
            Quartz.CFMachPortInvalidate(self.hotkey_event_tap)
        self.hotkey_event_tap = None
        self.hotkey_event_tap_location = None
        self.hotkey_event_tap_source = None
        self.hotkey_event_tap_callback = None
        self.hotkey_activated = False

    @objc.python_method
    def _restart_hotkey_monitor(self) -> None:
        """
        スリープ復帰後に失効することがあるホットキー監視を張り直す。
        """
        self._stop_hotkey_monitor()
        self._start_hotkey_monitor()

    @objc.python_method
    def _start_power_state_monitor(self) -> None:
        """
        macOS のスリープ/復帰通知を監視し、復帰時にホットキーを再登録する。
        """
        if self.power_notifications_registered:
            return
        notification_center = AppKit.NSWorkspace.sharedWorkspace().notificationCenter()
        notification_center.addObserver_selector_name_object_(
            self,
            "workspaceWillSleep:",
            AppKit.NSWorkspaceWillSleepNotification,
            None,
        )
        notification_center.addObserver_selector_name_object_(
            self,
            "workspaceDidWake:",
            AppKit.NSWorkspaceDidWakeNotification,
            None,
        )
        self.power_notification_center = notification_center
        self.power_notifications_registered = True

    def workspaceWillSleep_(self, notification: Any) -> None:
        """
        スリープ直前に修飾キーの押下状態をクリアする。
        """
        self.hotkey_activated = False

    def workspaceDidWake_(self, notification: Any) -> None:
        """
        スリープ復帰後にグローバルホットキー監視を再登録する。
        """
        self._restart_hotkey_monitor()

    @objc.python_method
    def _handle_modifier_event(self, event: Any) -> None:
        """
        Command + Option が揃った瞬間にだけ表示状態を切り替える。
        """
        self._handle_modifier_flags(event.modifierFlags())

    @objc.python_method
    def _handle_modifier_flags(self, flags: int) -> None:
        """
        修飾キーの bit flag から Command + Option の押下状態を判定する。
        """
        required = AppKit.NSEventModifierFlagCommand | AppKit.NSEventModifierFlagOption
        active = (flags & required) == required
        if active and not self.hotkey_activated:
            self.hotkey_activated = True
            AppHelper.callAfter(self.toggle_panel)
        elif not active:
            self.hotkey_activated = False

    @objc.python_method
    def _panel_collection_behavior(self) -> int:
        """
        仮想デスクトップやフルスクリーン上でも表示するための挙動を返す。
        """
        return (
            AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
            | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
            | AppKit.NSWindowCollectionBehaviorStationary
            | getattr(AppKit, "NSWindowCollectionBehaviorTransient", 0)
        )

    @objc.python_method
    def _prepare_panel_for_active_space(self) -> None:
        """
        時間経過後も現在の仮想デスクトップへ出るように表示属性を張り直す。
        """
        self.panel.setCollectionBehavior_(self._panel_collection_behavior())
        self.panel.setLevel_(AppKit.NSStatusWindowLevel)
        self.panel.setHidesOnDeactivate_(False)
        if self.panel.isMiniaturized():
            self.panel.deminiaturize_(None)

    @objc.python_method
    def _begin_activity(self) -> None:
        """
        常駐ランチャーが App Nap で眠らないように activity token を保持する。
        """
        if self.activity_token is not None:
            return
        process_info = AppKit.NSProcessInfo.processInfo()
        options = (
            getattr(AppKit, "NSActivityUserInitiatedAllowingIdleSystemSleep", 0)
            | getattr(AppKit, "NSActivityLatencyCritical", 0)
        )
        self.activity_token = process_info.beginActivityWithOptions_reason_(
            options,
            "Local Fulltext Search launcher hotkey monitor",
        )

    @objc.python_method
    def show_panel(self) -> None:
        """
        現在の仮想デスクトップ上にパネルを表示する。
        """
        self._prepare_panel_for_active_space()
        self.panel.orderOut_(None)
        self._center_panel_on_mouse_screen()
        self.panel.setAlphaValue_(1.0)
        AppKit.NSApp.activateIgnoringOtherApps_(True)
        self.panel.makeKeyWindow()
        self.panel.makeKeyAndOrderFront_(None)
        self.panel.orderFrontRegardless()
        self._focus_active_screen()

    @objc.python_method
    def hide_panel(self) -> None:
        """
        セッションを維持したままパネルを閉じる。
        """
        self.panel.orderOut_(None)

    def windowDidResignKey_(self, notification: Any) -> None:
        """
        フォーカス喪失時にパネルを自動で隠す。
        """
        if self.panel is not None and self.panel.isVisible():
            self.hide_panel()

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
        self.panel.setDelegate_(self)
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(AppKit.NSColor.clearColor())
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setMovableByWindowBackground_(True)
        self.panel.setCollectionBehavior_(self._panel_collection_behavior())

        content = AppKit.NSView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, PANEL_WIDTH, PANEL_HEIGHT))
        content.setWantsLayer_(True)
        content.layer().setCornerRadius_(24)
        content.layer().setBackgroundColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.06, 0.09, 0.16, 0.96).CGColor())
        content.layer().setBorderColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.22, 0.48, 1.0, 0.9).CGColor())
        content.layer().setBorderWidth_(1.0)
        self.panel.setContentView_(content)

        self.search_field = AppKit.NSSearchField.alloc().initWithFrame_(AppKit.NSMakeRect(34, PANEL_HEIGHT - 80, PANEL_WIDTH - 68, 36))
        self.search_field.setDelegate_(self)
        self.search_field.setPlaceholderString_("検索語を入力")
        self.search_field.setFont_(AppKit.NSFont.systemFontOfSize_weight_(20, AppKit.NSFontWeightRegular))
        self.search_field.setTextColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.9, 0.94, 1.0, 1.0))
        self.search_field.setDrawsBackground_(False)
        content.addSubview_(self.search_field)

        self.gui_button = AppKit.NSButton.buttonWithTitle_target_action_("Web GUI", self, "openGuiUrl:")
        self.gui_button.setFrame_(AppKit.NSMakeRect(34, PANEL_HEIGHT - 36, 80, 24))
        self.gui_button.setBezelStyle_(AppKit.NSBezelStyleRounded)
        content.addSubview_(self.gui_button)

        self.gantt_checkbox = AppKit.NSButton.checkboxWithTitle_target_action_("gantt", self, "toggleGanttSearch:")
        self.gantt_checkbox.setFrame_(AppKit.NSMakeRect(126, PANEL_HEIGHT - 36, 80, 24))
        content.addSubview_(self.gantt_checkbox)

        self.search_scroll = AppKit.NSScrollView.alloc().initWithFrame_(AppKit.NSMakeRect(24, 54, PANEL_WIDTH - 48, PANEL_HEIGHT - 158))
        self.search_scroll.setDrawsBackground_(False)
        self.search_scroll.setBorderType_(AppKit.NSNoBorder)
        self.search_scroll.setHasVerticalScroller_(True)
        self.results_stack = FlippedView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, PANEL_WIDTH - 66, PANEL_HEIGHT - 158))
        self.search_scroll.setDocumentView_(self.results_stack)
        content.addSubview_(self.search_scroll)

        self.memo_title_label = AppKit.NSTextField.labelWithString_("gantt メモ")
        self.memo_title_label.setFrame_(AppKit.NSMakeRect(34, PANEL_HEIGHT - 34, 160, 20))
        self.memo_title_label.setTextColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.9, 0.94, 1.0, 1.0))
        self.memo_title_label.setFont_(AppKit.NSFont.boldSystemFontOfSize_(14))
        self.memo_title_label.setHidden_(True)
        content.addSubview_(self.memo_title_label)

        self.memo_parent_label = AppKit.NSTextField.labelWithString_(f"parent: {self.gantt_parent}")
        self.memo_parent_label.setFrame_(AppKit.NSMakeRect(PANEL_WIDTH - 214, PANEL_HEIGHT - 34, 180, 20))
        self.memo_parent_label.setTextColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.73, 0.86, 1.0, 1.0))
        self.memo_parent_label.setHidden_(True)
        content.addSubview_(self.memo_parent_label)

        # タスク名入力欄 (NSTextField)
        self.memo_title_field = AppKit.NSTextField.alloc().initWithFrame_(AppKit.NSMakeRect(24, PANEL_HEIGHT - 80, PANEL_WIDTH - 48, 36))
        self.memo_title_field.setBezelStyle_(AppKit.NSTextFieldSquareBezel)
        self.memo_title_field.setPlaceholderString_("タスク名を入力してください...")
        self.memo_title_field.setFont_(AppKit.NSFont.systemFontOfSize_(16))
        self.memo_title_field.setTextColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.9, 0.94, 1.0, 1.0))
        self.memo_title_field.setDrawsBackground_(True)
        self.memo_title_field.setBackgroundColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.07, 0.09, 0.15, 0.98))
        self.memo_title_field.setDelegate_(self)
        self.memo_title_field.setHidden_(True)
        content.addSubview_(self.memo_title_field)

        # メモ入力部 (NSTextView)
        self.memo_body_view = AppKit.NSTextView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, PANEL_WIDTH - 48, PANEL_HEIGHT - 220))
        self.memo_body_view.setDelegate_(self)
        self.memo_body_view.setFont_(AppKit.NSFont.systemFontOfSize_(14))
        self.memo_body_view.setTextColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.9, 0.94, 1.0, 1.0))
        self.memo_body_view.setBackgroundColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.07, 0.09, 0.15, 0.98))
        self.memo_body_view.setInsertionPointColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.38, 0.65, 0.98, 1.0))
        self.memo_body_view.setString_("")
        
        # メモ用スクロールビュー
        self.memo_scroll = AppKit.NSScrollView.alloc().initWithFrame_(AppKit.NSMakeRect(24, 90, PANEL_WIDTH - 48, PANEL_HEIGHT - 220))
        self.memo_scroll.setDrawsBackground_(False)
        self.memo_scroll.setBorderType_(AppKit.NSNoBorder)
        self.memo_scroll.setHasVerticalScroller_(True)
        self.memo_scroll.setDocumentView_(self.memo_body_view)
        self.memo_scroll.setHidden_(True)
        content.addSubview_(self.memo_scroll)

        # 送信ボタン
        self.memo_submit_button = AppKit.NSButton.buttonWithTitle_target_action_("送信", self, "submitMemo:")
        self.memo_submit_button.setFrame_(AppKit.NSMakeRect(PANEL_WIDTH - 120, 50, 96, 32))
        self.memo_submit_button.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self.memo_submit_button.setHidden_(True)
        content.addSubview_(self.memo_submit_button)

        # キャンセルボタン
        self.memo_cancel_button = AppKit.NSButton.buttonWithTitle_target_action_("キャンセル", self, "cancelMemo:")
        self.memo_cancel_button.setFrame_(AppKit.NSMakeRect(PANEL_WIDTH - 226, 50, 96, 32))
        self.memo_cancel_button.setBezelStyle_(AppKit.NSBezelStyleRounded)
        self.memo_cancel_button.setHidden_(True)
        content.addSubview_(self.memo_cancel_button)

        # Cocoa 標準のフォーカス移動チェーンの構築
        self.memo_title_field.setNextKeyView_(self.memo_body_view)
        self.memo_body_view.setNextKeyView_(self.memo_submit_button)
        self.memo_submit_button.setNextKeyView_(self.memo_cancel_button)
        self.memo_cancel_button.setNextKeyView_(self.memo_title_field)

        self.status_label = AppKit.NSTextField.labelWithString_(f"Hotkey: {hotkey_spec_for_platform()}")
        self.status_label.setFrame_(AppKit.NSMakeRect(34, 22, PANEL_WIDTH - 68, 20))
        self.status_label.setTextColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.58, 0.64, 0.73, 1.0))
        self.status_label.setFont_(AppKit.NSFont.boldSystemFontOfSize_(13))
        content.addSubview_(self.status_label)

    @objc.python_method
    def _switch_screen(self, screen: str) -> None:
        """
        Tab キーで検索画面と gantt メモ画面を切り替える。
        """
        self.active_screen = "memo" if screen == "memo" else "search"
        is_memo = self.active_screen == "memo"
        self.search_field.setHidden_(is_memo)
        self.gui_button.setHidden_(is_memo)
        self.gantt_checkbox.setHidden_(is_memo)
        self.search_scroll.setHidden_(is_memo)
        self.memo_scroll.setHidden_(not is_memo)
        self.memo_title_label.setHidden_(not is_memo)
        self.memo_parent_label.setHidden_(not is_memo)
        self.memo_title_field.setHidden_(not is_memo)
        self.memo_submit_button.setHidden_(not is_memo)
        self.memo_cancel_button.setHidden_(not is_memo)
        self.status_label.setStringValue_("gantt メモ" if is_memo else f"Hotkey: {hotkey_spec_for_platform()}")
        self._focus_active_screen()

    @objc.python_method
    def _focus_active_screen(self) -> None:
        """
        現在表示中の画面に対応する入力欄へフォーカスを戻す。
        """
        if self.active_screen == "memo" and self.memo_title_field is not None:
            self.panel.makeFirstResponder_(self.memo_title_field)
            return
        if self.search_field is not None:
            self.panel.makeFirstResponder_(self.search_field)

    @objc.python_method
    def _submit_memo(self) -> None:
        """
        メモ入力を gantt タスク作成 API へ送る。
        """
        title = str(self.memo_title_field.stringValue() or "").strip()
        memo = str(self.memo_body_view.string() or "").strip()
        if not title:
            self.status_label.setStringValue_("タスク名を入力してください")
            return
        parent = self._load_gantt_parent()
        payload = build_gantt_task_payload(title, memo, parent=parent)
        try:
            self.client.create_gantt_task(payload)
        except Exception as error:
            self.status_label.setStringValue_(f"gantt 追加に失敗しました: {error}")
        else:
            self.memo_title_field.setStringValue_("")
            self.memo_body_view.setString_("")
            self.status_label.setStringValue_("gantt に追加しました")
            self.panel.makeFirstResponder_(self.memo_title_field)

    def submitMemo_(self, sender: Any) -> None:
        """
        Cocoa の送信ボタン押下時のアクション。
        """
        self._submit_memo()

    def cancelMemo_(self, sender: Any) -> None:
        """
        Cocoa のキャンセルボタン押下時のアクション。
        """
        self._switch_screen("search")

    @objc.python_method
    def _load_gantt_parent(self) -> int:
        """
        Web の設定ドロワーで保存した gantt parent ID を取得する。
        """
        try:
            app_settings = self.client.get_app_settings()
        except Exception:
            return self.gantt_parent
        self.gantt_parent = normalize_parent_id(app_settings.get("gantt_parent"), default=self.gantt_parent)
        self.memo_parent_label.setStringValue_(f"parent: {self.gantt_parent}")
        return self.gantt_parent

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
            response = self.client.search(query, limit=self.config.search_limit, include_gantt_tasks=self.include_gantt_tasks)
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
        self.last_results_time = time.time()
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
        self.last_results_time = time.time()
        self._render_results()

    @objc.python_method
    def _render_results(self) -> None:
        """
        現在の検索結果をクリック可能なカードとして描画する。
        """
        for view in list(self.results_stack.subviews()):
            view.removeFromSuperview()
        
        card_height = 64
        spacing = 8
        total_height = len(self.results) * (card_height + spacing)
        new_height = max(PANEL_HEIGHT - 158, total_height)
        self.results_stack.setFrameSize_(AppKit.NSMakeSize(PANEL_WIDTH - 66, new_height))

        for index, item in enumerate(self.results):
            card = self._make_result_card(item, index, index == self.selected_index)
            card.setFrameOrigin_(AppKit.NSMakePoint(4, index * (card_height + spacing)))
            self.results_stack.addSubview_(card)

    @objc.python_method
    def _update_card_selection(self, old_index: int, new_index: int) -> None:
        """
        選択変更時にカード全体を再構築せず、背景色とボーダー色のみを更新する。
        """
        subviews = self.results_stack.subviews()
        count = len(subviews)
        if old_index < count:
            self._apply_card_style(subviews[old_index], selected=False)
        if new_index < count:
            self._apply_card_style(subviews[new_index], selected=True)

    @objc.python_method
    def _apply_card_style(self, card: AppKit.NSView, *, selected: bool) -> None:
        """
        カードの背景色・ボーダー色・パスラベル色・タイトル色を選択状態に応じて更新する。
        """
        bg = (0.11, 0.31, 0.85, 0.98) if selected else (0.07, 0.09, 0.15, 0.98)
        border = (0.38, 0.65, 0.98, 0.9) if selected else (0.12, 0.16, 0.22, 0.9)
        card.layer().setBackgroundColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(*bg).CGColor())
        card.layer().setBorderColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(*border).CGColor())
        
        subviews = card.subviews()
        # 新しいサブビュー順序:
        # 0: title, 1: path, 2: snippet, 3: invisible_button, 4: copy, 5: finder, 6: folder
        if len(subviews) > 1:
            # Title
            title_color = (1.0, 1.0, 1.0, 1.0) if selected else (0.38, 0.80, 0.98, 1.0) # 選択時は白、非選択時は水色(リンク風)
            subviews[0].setTextColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(*title_color))
            
            # Path
            path_color = (0.7, 0.8, 1.0, 1.0) if selected else (0.58, 0.64, 0.73, 1.0)
            subviews[1].setTextColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(*path_color))

    @objc.python_method
    def _make_result_card(self, item: SearchResultItem, index: int, selected: bool) -> AppKit.NSView:
        """
        検索結果 1 件を Web アプリの結果カードに近い操作群として描画する。
        ボタンの tag にはリスト内インデックスを使い、file_id 衝突を回避する。
        """
        card = FlippedView.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, PANEL_WIDTH - 74, 64))
        card.setWantsLayer_(True)
        color = (0.11, 0.31, 0.85, 0.98) if selected else (0.07, 0.09, 0.15, 0.98)
        card.layer().setBackgroundColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(*color).CGColor())
        card.layer().setCornerRadius_(8)
        border_color = (0.38, 0.65, 0.98, 0.9) if selected else (0.12, 0.16, 0.22, 0.9)
        card.layer().setBorderColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(*border_color).CGColor())
        card.layer().setBorderWidth_(1.0)

        title_label = AppKit.NSTextField.labelWithString_(item.file_name)
        title_label.setFrame_(AppKit.NSMakeRect(16, 6, PANEL_WIDTH - 340, 20))
        title_color = (1.0, 1.0, 1.0, 1.0) if selected else (0.38, 0.80, 0.98, 1.0) # 水色でリンクっぽく
        title_label.setTextColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(*title_color))
        title_label.setFont_(AppKit.NSFont.boldSystemFontOfSize_(14))
        title_label.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
        card.addSubview_(title_label)

        path_label = AppKit.NSTextField.labelWithString_(item.full_path)
        path_label.setFrame_(AppKit.NSMakeRect(16, 26, PANEL_WIDTH - 340, 14))
        path_color = (0.7, 0.8, 1.0, 1.0) if selected else (0.58, 0.64, 0.73, 1.0)
        path_label.setTextColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(*path_color))
        path_label.setFont_(AppKit.NSFont.systemFontOfSize_(10))
        path_label.setLineBreakMode_(AppKit.NSLineBreakByTruncatingMiddle)
        card.addSubview_(path_label)

        snippet = strip_html(item.snippet)[:120].replace("\n", " ")
        snippet_label = AppKit.NSTextField.labelWithString_(snippet)
        snippet_label.setFrame_(AppKit.NSMakeRect(16, 42, PANEL_WIDTH - 340, 16))
        snippet_label.setTextColor_(AppKit.NSColor.colorWithCalibratedRed_green_blue_alpha_(0.8, 0.83, 0.88, 1.0))
        snippet_label.setFont_(AppKit.NSFont.systemFontOfSize_(11))
        snippet_label.setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
        snippet_label.setMaximumNumberOfLines_(1)
        card.addSubview_(snippet_label)

        # クリック全体を覆う透明ボタンを前面（テキストの上）に配置
        invisible_button = AppKit.NSButton.alloc().initWithFrame_(AppKit.NSMakeRect(0, 0, PANEL_WIDTH - 320, 64))
        invisible_button.setTitle_("")
        invisible_button.setTransparent_(True)
        invisible_button.setTarget_(self)
        invisible_button.setAction_("openResult:")
        invisible_button.setTag_(index)
        card.addSubview_(invisible_button)

        if item.source_type == "gantt":
            if item.gantt_link:
                link_button = AppKit.NSButton.buttonWithTitle_target_action_("ganttのリンクを開く", self, "openGanttLinkResult:")
                link_button.setFrame_(AppKit.NSMakeRect(PANEL_WIDTH - 236, 20, 162, 24))
                link_button.setTag_(index)
                link_button.setBezelStyle_(AppKit.NSBezelStyleRounded)
                card.addSubview_(link_button)
        else:
            copy_button = AppKit.NSButton.buttonWithTitle_target_action_("フルパス", self, "copyPathResult:")
            copy_button.setFrame_(AppKit.NSMakeRect(PANEL_WIDTH - 316, 20, 68, 24))
            copy_button.setTag_(index)
            copy_button.setBezelStyle_(AppKit.NSBezelStyleRounded)
            card.addSubview_(copy_button)

            finder_button = AppKit.NSButton.buttonWithTitle_target_action_("Finderで開く", self, "revealResult:")
            finder_button.setFrame_(AppKit.NSMakeRect(PANEL_WIDTH - 240, 20, 76, 24))
            finder_button.setTag_(index)
            finder_button.setBezelStyle_(AppKit.NSBezelStyleRounded)
            card.addSubview_(finder_button)

            folder_button = AppKit.NSButton.buttonWithTitle_target_action_("フォルダを開く", self, "openFolderResult:")
            folder_button.setFrame_(AppKit.NSMakeRect(PANEL_WIDTH - 156, 20, 82, 24))
            folder_button.setTag_(index)
            folder_button.setBezelStyle_(AppKit.NSBezelStyleRounded)
            card.addSubview_(folder_button)
        
        return card

    def openResult_(self, sender: Any) -> None:
        """
        Web アプリのタイトルリンクと同じ URL を既定ブラウザで開く。
        """
        index = int(sender.tag())
        if index < 0 or index >= len(self.results):
            return
        self._open_item(self.results[index])

    @objc.python_method
    def _open_item(self, item: SearchResultItem) -> None:
        try:
            if item.source_type == "gantt":
                self.client.open_gantt_task_input(abs(item.file_id))
                self.hide_panel()
                return
            webbrowser.open(primary_web_url_for_item(item, self.web_base_url))
            if item.result_kind == "file" and item.source_type != "gantt" and item.file_id > 0:
                query = str(self.search_field.stringValue()).strip() if self.search_field is not None else ""
                self.client.record_click(item.file_id, query)
            self.hide_panel()
        except Exception as error:
            self.status_label.setStringValue_(f"ファイルを開けませんでした: {error}")

    def revealResult_(self, sender: Any) -> None:
        """
        Web アプリの Finder で開くボタンと同じ backend API を呼ぶ。
        """
        index = int(sender.tag())
        if index < 0 or index >= len(self.results):
            return
        item = self.results[index]
        target_path = item.full_path if item.result_kind == "folder" else folder_path_for_item(item)
        try:
            self.client.open_location(target_path)
        except Exception as error:
            self.status_label.setStringValue_(f"保存場所を開けませんでした: {error}")

    def copyPathResult_(self, sender: Any) -> None:
        """
        フルパスをクリップボードにコピーする。
        """
        index = int(sender.tag())
        if index < 0 or index >= len(self.results):
            return
        item = self.results[index]
        pasteboard = AppKit.NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        pasteboard.setString_forType_(item.full_path, AppKit.NSPasteboardTypeString)
        self.status_label.setStringValue_("クリップボードにコピーしました")

    def toggleGanttSearch_(self, sender: Any) -> None:
        """
        macOS ランチャーで gantt タスク検索の有効/無効を切り替える。
        """
        self.include_gantt_tasks = bool(sender.state())
        if self.search_field is not None and str(self.search_field.stringValue()).strip():
            self.controlTextDidChange_(None)

    def openFolderResult_(self, sender: Any) -> None:
        """
        Web アプリのフォルダリンクと同じ URL を既定ブラウザで開く。
        """
        index = int(sender.tag())
        if index < 0 or index >= len(self.results):
            return
        item = self.results[index]
        webbrowser.open(folder_web_url_for_item(item, self.web_base_url))

    def openGanttLinkResult_(self, sender: Any) -> None:
        """
        gantt タスクに設定されているリンクを既定ブラウザで開く。
        """
        index = int(sender.tag())
        if index < 0 or index >= len(self.results):
            return
        item = self.results[index]
        if item.gantt_link:
            webbrowser.open(item.gantt_link)

    def openGuiUrl_(self, sender: Any) -> None:
        """
        GUIへのリンクを既定ブラウザで開く。
        """
        webbrowser.open("http://127.0.0.1:8079/")
        self.hide_panel()


def run_native_mac_app(config: LauncherConfig | None = None) -> None:
    """
    macOS ネイティブパネルとしてランチャーを起動する。
    """
    if platform.system() != "Darwin":
        raise RuntimeError("Native macOS launcher is only available on Darwin.")
    app_config = config or LauncherConfig.from_env()
    client = LauncherApiClient(
        app_config.api_base_url,
        gantt_api_base_url=app_config.gantt_api_base_url,
        timeout=app_config.request_timeout,
    )
    global _delegate_ref
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)

    # Cmd+C, Cmd+V などの標準ショートカットを有効にするため、ダミーのEditメニューを登録する
    menubar = AppKit.NSMenu.alloc().init()
    app_menu_item = AppKit.NSMenuItem.alloc().init()
    menubar.addItem_(app_menu_item)
    
    edit_menu_item = AppKit.NSMenuItem.alloc().init()
    edit_menu = AppKit.NSMenu.alloc().initWithTitle_("Edit")
    edit_menu.addItemWithTitle_action_keyEquivalent_("Cut", "cut:", "x")
    edit_menu.addItemWithTitle_action_keyEquivalent_("Copy", "copy:", "c")
    edit_menu.addItemWithTitle_action_keyEquivalent_("Paste", "paste:", "v")
    edit_menu.addItemWithTitle_action_keyEquivalent_("Select All", "selectAll:", "a")
    edit_menu.addItemWithTitle_action_keyEquivalent_("Undo", "undo:", "z")
    edit_menu_item.setSubmenu_(edit_menu)
    menubar.addItem_(edit_menu_item)
    app.setMainMenu_(menubar)

    delegate = LauncherDelegate.alloc().initWithClient_config_(client, app_config)
    _delegate_ref = delegate
    delegate._begin_activity()
    delegate._build_panel()
    delegate._start_hotkey_monitor()
    delegate._start_power_state_monitor()
    delegate.status_label.setStringValue_(f"Hotkey: {hotkey_spec_for_platform()}")
    app.setDelegate_(delegate)
    delegate.show_panel()
    AppHelper.runEventLoop()
