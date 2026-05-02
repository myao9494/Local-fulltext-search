"""
ランチャーの UI 層で共通して使うユーティリティ関数を提供する。
"""

import html
import re


def strip_html(value: str) -> str:
    """
    API スニペットの HTML タグ（mark 等）を除去し、プレーンテキストへ変換する。
    """
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()
