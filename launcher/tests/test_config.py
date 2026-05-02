"""
LauncherConfig が環境変数を正しく読み取ることを検証する。
"""

import os

from launcher_app.config import LauncherConfig


def test_default_config_values() -> None:
    """
    環境変数未指定時はローカル開発用の既定値を返す。
    """
    config = LauncherConfig()

    assert config.api_base_url == "http://127.0.0.1:8079"
    assert config.web_base_url == "http://127.0.0.1:8079"
    assert config.search_limit == 8
    assert config.request_timeout == 5.0


def test_from_env_reads_api_base_url(monkeypatch) -> None:
    """
    LAUNCHER_API_BASE_URL が設定されていれば既定値を上書きする。
    """
    monkeypatch.setenv("LAUNCHER_API_BASE_URL", "http://example.com:9999")

    config = LauncherConfig.from_env()

    assert config.api_base_url == "http://example.com:9999"


def test_from_env_reads_web_base_url(monkeypatch) -> None:
    """
    LAUNCHER_WEB_BASE_URL が設定されていれば既定値を上書きする。
    """
    monkeypatch.setenv("LAUNCHER_WEB_BASE_URL", "http://myhost:3000")

    config = LauncherConfig.from_env()

    assert config.web_base_url == "http://myhost:3000"


def test_from_env_ignores_invalid_int(monkeypatch) -> None:
    """
    不正な整数値の環境変数は無視して既定値を返す。
    """
    monkeypatch.setenv("LAUNCHER_SEARCH_LIMIT", "abc")

    config = LauncherConfig.from_env()

    assert config.search_limit == 8


def test_from_env_ignores_negative_int(monkeypatch) -> None:
    """
    負の整数値の環境変数は無視して既定値を返す。
    """
    monkeypatch.setenv("LAUNCHER_SEARCH_LIMIT", "-3")

    config = LauncherConfig.from_env()

    assert config.search_limit == 8


def test_from_env_ignores_invalid_float(monkeypatch) -> None:
    """
    不正な小数値の環境変数は無視して既定値を返す。
    """
    monkeypatch.setenv("LAUNCHER_REQUEST_TIMEOUT", "not_a_number")

    config = LauncherConfig.from_env()

    assert config.request_timeout == 5.0


def test_from_env_ignores_negative_float(monkeypatch) -> None:
    """
    負の小数値の環境変数は無視して既定値を返す。
    """
    monkeypatch.setenv("LAUNCHER_REQUEST_TIMEOUT", "-1.5")

    config = LauncherConfig.from_env()

    assert config.request_timeout == 5.0


def test_from_env_accepts_valid_values(monkeypatch) -> None:
    """
    有効な値はすべて正しく反映される。
    """
    monkeypatch.setenv("LAUNCHER_SEARCH_LIMIT", "20")
    monkeypatch.setenv("LAUNCHER_REQUEST_TIMEOUT", "10.5")

    config = LauncherConfig.from_env()

    assert config.search_limit == 20
    assert config.request_timeout == 10.5
