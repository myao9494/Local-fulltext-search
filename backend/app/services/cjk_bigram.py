"""
日本語の連続文字列を SQLite FTS5 で補助検索するための bi-gram ヘルパー。

unicode61 既定トークナイザでは「今日はお寿司が食べたい」のような本文が
1トークン相当として扱われやすく、「寿司」のような部分一致を拾えない。
そのため、日本語連続文字列から 2 文字ずつ重なるトークン列を作り、
補助セグメントのインデックスと検索クエリ変換の両方で共通利用する。
"""

from __future__ import annotations


def build_cjk_bigram_index_content(content: str) -> str:
    """
    補助セグメント用に元本文と bi-gram 列を 1 つの文字列へまとめる。

    ASCII 語との混在 AND 検索も同じセグメントで評価できるよう、
    元本文も先頭に残したうえで末尾へ bi-gram トークン列を付与する。
    """
    tokens = build_cjk_bigram_tokens(content)
    if not tokens:
        return ""
    return f"{content}\n{' '.join(tokens)}"


def build_cjk_bigram_match_query(value: str) -> str | None:
    """
    日本語語を含む検索語だけ bi-gram フレーズへ変換し、空白区切り AND を維持する。
    """
    terms = [term for term in value.split() if term]
    if not terms:
        return None

    uses_bigram = False
    query_terms: list[str] = []
    for term in terms:
        if _is_bigram_target_term(term):
            uses_bigram = True
            query_terms.append(_quote_fts_phrase(build_cjk_bigram_tokens(term)))
            continue
        query_terms.append(_quote_fts_term(term))

    if not uses_bigram:
        return None
    return " AND ".join(query_terms)


def build_cjk_bigram_tokens(value: str) -> list[str]:
    """
    日本語の連続部分だけを取り出し、重なりあり 2 文字トークン列へ変換する。
    """
    tokens: list[str] = []
    current: list[str] = []
    for char in value:
        if _is_cjk_bigram_char(char):
            current.append(char)
            continue
        tokens.extend(_build_bigrams(current))
        current.clear()
    tokens.extend(_build_bigrams(current))
    return tokens


def has_cjk_bigram_tokens(value: str) -> bool:
    """
    bi-gram 補助インデックスが必要な日本語連続文字列を含むか判定する。
    """
    run_length = 0
    for char in value:
        if _is_cjk_bigram_char(char):
            run_length += 1
            if run_length >= 2:
                return True
            continue
        run_length = 0
    return False


def _is_bigram_target_term(term: str) -> bool:
    return len(term) >= 2 and all(_is_cjk_bigram_char(char) for char in term)


def _build_bigrams(chars: list[str]) -> list[str]:
    if len(chars) < 2:
        return []
    return ["".join(chars[index : index + 2]) for index in range(len(chars) - 1)]


def _quote_fts_term(term: str) -> str:
    escaped_term = term.replace('"', '""')
    return f'"{escaped_term}"'


def _quote_fts_phrase(tokens: list[str]) -> str:
    escaped_phrase = " ".join(token.replace('"', '""') for token in tokens)
    return f'"{escaped_phrase}"'


def _is_cjk_bigram_char(char: str) -> bool:
    """
    かな・カナ・漢字・一部の日本語反復記号を bi-gram 対象文字として扱う。
    """
    codepoint = ord(char)
    return (
        0x3040 <= codepoint <= 0x309F  # ひらがな
        or 0x30A0 <= codepoint <= 0x30FF  # カタカナ
        or 0x3400 <= codepoint <= 0x4DBF  # CJK 拡張A
        or 0x4E00 <= codepoint <= 0x9FFF  # CJK 統合漢字
        or 0xF900 <= codepoint <= 0xFAFF  # CJK 互換漢字
        or 0xFF66 <= codepoint <= 0xFF9F  # 半角カタカナ
        or codepoint in {0x3005, 0x3006, 0x303B}  # 々, 〆, 〻
    )
