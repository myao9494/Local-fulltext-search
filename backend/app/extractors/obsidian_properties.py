"""
Obsidian Markdown のフロントマターにある検索順位用プロパティを判定する。
外部 YAML ライブラリに依存せず、tag / tags の一般的な記法を扱う。
"""

from __future__ import annotations

import re


def extract_obsidian_title_and_aliases(content: str) -> tuple[str, tuple[str, ...]]:
    """
    先頭フロントマターから title と aliases/alias を検索用文字列として取り出す。
    """
    frontmatter = re.match(r"\A---[ \t]*\r?\n(.*?)(?:\r?\n---[ \t]*(?:\r?\n|\Z))", content, re.DOTALL)
    if frontmatter is None:
        return "", ()
    lines = frontmatter.group(1).splitlines()
    title = ""
    aliases: list[str] = []
    index = 0
    while index < len(lines):
        match = re.match(r"^[ \t]*(title|alias|aliases)[ \t]*:[ \t]*(.*)$", lines[index], re.IGNORECASE)
        if match is None:
            index += 1
            continue
        key = match.group(1).casefold()
        values = _split_property_values(match.group(2))
        index += 1
        while index < len(lines):
            list_item = re.match(r"^[ \t]+-[ \t]*(.*)$", lines[index])
            if list_item is None:
                break
            values.extend(_split_property_values(list_item.group(1)))
            index += 1
        if key == "title" and values:
            title = values[0]
        elif key in {"alias", "aliases"}:
            aliases.extend(values)
    return title, tuple(dict.fromkeys(value for value in aliases if value))


def _split_property_values(value: str) -> list[str]:
    """
    YAMLの単一値・インライン配列を、引用符を除いた値へ正規化する。
    """
    return [token.strip().strip("[]'\" ") for token in value.split(",") if token.strip().strip("[]'\" ")]


def has_obsidian_top_tag(content: str) -> bool:
    """
    先頭フロントマターの tag または tags プロパティに top があるかを返す。
    インライン配列と、改行ごとの YAML 配列のどちらも大文字小文字を区別せず判定する。
    """
    frontmatter = re.match(r"\A---[ \t]*\r?\n(.*?)(?:\r?\n---[ \t]*(?:\r?\n|\Z))", content, re.DOTALL)
    if frontmatter is None:
        return False

    lines = frontmatter.group(1).splitlines()
    index = 0
    while index < len(lines):
        property_match = re.match(r"^[ \t]*(?:tag|tags)[ \t]*:[ \t]*(.*)$", lines[index], re.IGNORECASE)
        if property_match is None:
            index += 1
            continue

        values = [property_match.group(1)]
        index += 1
        while index < len(lines):
            list_item = re.match(r"^[ \t]+-[ \t]*(.*)$", lines[index])
            if list_item is None:
                break
            values.append(list_item.group(1))
            index += 1
        return any(_is_top_tag(value) for value in values)
    return False


def _is_top_tag(value: str) -> bool:
    """
    tag 値の配列記法・単一値記法から、完全一致する top を検出する。
    """
    return any(
        token.strip().strip("[]'\" ").lstrip("#").casefold() == "top"
        for token in value.split(",")
    )
