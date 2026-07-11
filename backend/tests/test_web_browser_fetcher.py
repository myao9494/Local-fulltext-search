"""
Playwright で端末にインストール済みの Edge/Chrome を使う Web 取得処理を検証する。
"""

from pathlib import Path

import pytest

from app.services.web_browser_fetcher import BrowserWebFetcher, BrowserWebFetcherError


class _FakePage:
    def __init__(self) -> None:
        self.urls: list[str] = []

    def goto(self, url: str, **kwargs):
        self.urls.append(url)
        return object()

    def wait_for_load_state(self, *args, **kwargs) -> None:
        return None

    def content(self) -> str:
        return "<html><body>Edge rendered body</body></html>"


class _FakeContext:
    def __init__(self) -> None:
        self.pages = [_FakePage()]
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeChromium:
    def __init__(self, context: _FakeContext) -> None:
        self.context = context
        self.launch_options: dict[str, object] = {}

    def launch_persistent_context(self, **kwargs):
        self.launch_options = kwargs
        return self.context


class _FakePlaywright:
    def __init__(self, chromium: _FakeChromium) -> None:
        self.chromium = chromium


class _FakeManager:
    def __init__(self, playwright: _FakePlaywright) -> None:
        self.playwright = playwright
        self.stopped = False

    def start(self) -> _FakePlaywright:
        return self.playwright

    def stop(self) -> None:
        self.stopped = True


def test_browser_fetcher_uses_installed_edge_and_persistent_profile(tmp_path: Path) -> None:
    """
    Edge モードは msedge チャンネルと専用永続プロファイルを画面ありで起動する。
    """
    context = _FakeContext()
    chromium = _FakeChromium(context)
    manager = _FakeManager(_FakePlaywright(chromium))
    profile = tmp_path / "edge-profile"
    fetcher = BrowserWebFetcher(channel="msedge", profile_dir=profile, playwright_factory=lambda: manager)

    with fetcher:
        html = fetcher.fetch("https://intranet.example/docs")

    assert html == "<html><body>Edge rendered body</body></html>"
    assert chromium.launch_options["channel"] == "msedge"
    assert chromium.launch_options["user_data_dir"] == str(profile)
    assert chromium.launch_options["headless"] is False
    assert context.pages[0].urls == ["https://intranet.example/docs"]
    assert context.closed is True
    assert manager.stopped is True


def test_browser_fetcher_reports_missing_playwright_without_browser_download(tmp_path: Path) -> None:
    """
    Python パッケージがない場合は、ブラウザのダウンロードを促さず pip 導入方法を返す。
    """
    def missing_factory():
        raise ImportError("No module named playwright")

    fetcher = BrowserWebFetcher(
        channel="msedge",
        profile_dir=tmp_path / "edge-profile",
        playwright_factory=missing_factory,
    )

    with pytest.raises(BrowserWebFetcherError, match="pip install playwright"):
        with fetcher:
            pass

