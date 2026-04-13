"""
テキスト抽出ユーティリティ。
Markdown は画像リンクや通常リンクを検索しやすい平文へ整形し、括弧を含むパスも壊さず保持する。
"""

from pathlib import Path


SUPPORTED_EXTENSIONS: set[str] = {".md", ".json", ".txt"}


def supports_extension(path: Path) -> bool:
    """
    Phase 1 で扱う拡張子かどうかを返す。
    """
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def extract_text(path: Path) -> str:
    """
    ファイル種別に応じて検索用テキストを抽出する。
    Markdown は `![](...)` / `[](...)` を平文化して検索しやすくする。
    """
    content = path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix.lower() == ".md":
        return _flatten_markdown_inline_links(content)
    return content


def _flatten_markdown_inline_links(content: str) -> str:
    """
    Markdown のインライン画像/リンク記法を平文へ変換する。
    宛先パス中の括弧を深さ付きで読むため、`(flow)` のような文字を含んでも途中で切らない。
    """
    fragments: list[str] = []
    index = 0
    length = len(content)

    while index < length:
        parsed = _parse_markdown_inline_link(content, index)
        if parsed is None:
            fragments.append(content[index])
            index += 1
            continue

        label, destination, next_index = parsed
        replacement = " ".join(part for part in (label.strip(), destination.strip()) if part.strip())
        fragments.append(replacement)
        index = next_index

    return "".join(fragments)


def _parse_markdown_inline_link(content: str, start_index: int) -> tuple[str, str, int] | None:
    """
    指定位置が Markdown の `![](...)` または `[](...)` なら、その内容を返す。
    """
    index = start_index
    if content[index] == "!":
        index += 1
        if index >= len(content) or content[index] != "[":
            return None
    elif content[index] != "[":
        return None

    label, next_index = _read_bracket_content(content, index, "[", "]")
    if label is None or next_index >= len(content) or content[next_index] != "(":
        return None

    destination, end_index = _read_parenthesized_destination(content, next_index)
    if destination is None:
        return None

    return label, destination, end_index


def _read_bracket_content(
    content: str,
    start_index: int,
    opening: str,
    closing: str,
) -> tuple[str | None, int]:
    r"""
    単純な括弧ブロックを読み取る。
    `\]` のような Markdown エスケープだけを特別扱いし、Windows パスの `\` は保持する。
    """
    if content[start_index] != opening:
        return None, start_index

    index = start_index + 1
    parts: list[str] = []
    while index < len(content):
        char = content[index]
        if char == "\\" and index + 1 < len(content):
            escaped_char = content[index + 1]
            if escaped_char in {opening, closing, "\\"}:
                parts.append(escaped_char)
                index += 2
                continue
        if char == closing:
            return "".join(parts), index + 1
        parts.append(char)
        index += 1
    return None, start_index


def _read_parenthesized_destination(content: str, start_index: int) -> tuple[str | None, int]:
    r"""
    宛先の丸括弧を深さ付きで読み取る。
    `C:/tmp/a(test).png` のような ASCII 括弧を含むパスも正しく最後まで取得する。
    `\)` などの Markdown エスケープのみ展開し、Windows パスの `\` は維持する。
    """
    if content[start_index] != "(":
        return None, start_index

    index = start_index + 1
    depth = 1
    parts: list[str] = []
    while index < len(content):
        char = content[index]
        if char == "\\" and index + 1 < len(content):
            escaped_char = content[index + 1]
            if escaped_char in {"(", ")", "\\"}:
                parts.append(escaped_char)
                index += 2
                continue
        if char == "(":
            depth += 1
            parts.append(char)
            index += 1
            continue
        if char == ")":
            depth -= 1
            if depth == 0:
                return "".join(parts), index + 1
            parts.append(char)
            index += 1
            continue
        parts.append(char)
        index += 1

    return None, start_index
