"""
共通ユーティリティ関数 strip_html の動作を検証する。
"""

from launcher_app.utils import strip_html


def test_strip_html_removes_mark_tags() -> None:
    """
    FTS5 のハイライト用 mark タグを除去する。
    """
    assert strip_html("<mark>alpha</mark> beta") == "alpha beta"


def test_strip_html_unescapes_entities() -> None:
    """
    HTML エンティティをプレーンテキストへ変換する。
    """
    assert strip_html("a &amp; b &lt; c") == "a & b < c"


def test_strip_html_strips_whitespace() -> None:
    """
    前後の空白を除去する。
    """
    assert strip_html("  hello  ") == "hello"


def test_strip_html_handles_empty_string() -> None:
    """
    空文字列は空文字列を返す。
    """
    assert strip_html("") == ""


def test_strip_html_handles_nested_tags() -> None:
    """
    ネストされたタグもすべて除去する。
    """
    assert strip_html("<div><mark>text</mark></div>") == "text"
