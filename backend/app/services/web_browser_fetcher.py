"""
端末にインストール済みの Edge/Chrome を Playwright で操作し、JavaScript 描画後の HTML を取得する。

Playwright 同梱ブラウザは使用せず、企業管理された正式版ブラウザと専用の永続プロファイルを使う。
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable


class BrowserWebFetcherError(RuntimeError):
    """
    ブラウザ取得を開始または継続できない場合の利用者向けエラー。
    """


def _load_sync_playwright():
    """
    Playwright を任意依存として遅延ロードし、通常HTTPモードの起動を妨げない。
    """
    from playwright.sync_api import sync_playwright

    return sync_playwright()


class BrowserWebFetcher:
    """
    同一ブラウザページと永続プロファイルをクロール実行中だけ再利用する。
    """

    def __init__(
        self,
        *,
        channel: str,
        profile_dir: Path,
        timeout_milliseconds: int = 30_000,
        playwright_factory: Callable[[], object] = _load_sync_playwright,
    ) -> None:
        self.channel = channel
        self.profile_dir = profile_dir
        self.timeout_milliseconds = timeout_milliseconds
        self._playwright_factory = playwright_factory
        self._manager = None
        self._context = None
        self._page = None

    def __enter__(self) -> "BrowserWebFetcher":
        """
        画面ありの正式版 Edge/Chrome を専用プロファイルで起動する。
        """
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        try:
            self._manager = self._playwright_factory()
            playwright = self._manager.start()
            self._context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                channel=self.channel,
                headless=False,
                accept_downloads=False,
            )
            self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
            return self
        except ImportError as error:
            self.close()
            raise BrowserWebFetcherError(
                "Playwright が未導入です。社内の Python パッケージ配布元から "
                "'pip install playwright' を実行してください。'playwright install' は不要です。"
            ) from error
        except Exception as error:
            self.close()
            raise BrowserWebFetcherError(
                f"{self.channel} の起動に失敗しました。ブラウザのインストール状況と企業ポリシーを確認してください: {error}"
            ) from error

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def fetch(self, url: str) -> str:
        """
        URLへ移動し、JavaScript描画後のDOMをHTMLとして返す。
        """
        if self._page is None:
            raise BrowserWebFetcherError("ブラウザ取得セッションが開始されていません。")
        try:
            self._page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_milliseconds)
            try:
                self._page.wait_for_load_state("networkidle", timeout=min(self.timeout_milliseconds, 10_000))
            except Exception:
                # 常時通信するSPAでもDOM取得は継続する。
                pass
            return self._page.content()
        except Exception as error:
            raise BrowserWebFetcherError(f"Edge/Chrome でページを取得できませんでした: {error}") from error

    def close(self) -> None:
        """
        ブラウザと Playwright ドライバーを必ず終了する。
        """
        if self._context is not None:
            try:
                self._context.close()
            finally:
                self._context = None
                self._page = None
        if self._manager is not None:
            try:
                self._manager.stop()
            finally:
                self._manager = None
