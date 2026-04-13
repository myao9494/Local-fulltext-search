"""
Markdown 抽出の整形ルールを検証する。
画像リンクや通常リンクを平文化し、括弧を含むパスを壊さないことを担保する。
"""

from pathlib import Path

from app.extractors.text_extractor import extract_text


def test_extract_text_flattens_markdown_image_path_with_parentheses(tmp_path: Path) -> None:
    """
    Markdown 画像リンクの宛先に ASCII の丸括弧が含まれても、全文を保持して抽出する。
    """
    markdown_file = tmp_path / "sample.md"
    markdown_file.write_text(
        r"パーツの新規作成(流用) ![](C:\M222345\000_work\tehai_s\パーツの新規作成(flow).png)",
        encoding="utf-8",
    )

    extracted = extract_text(markdown_file)

    assert r"C:\M222345\000_work\tehai_s\パーツの新規作成(flow).png" in extracted
    assert "![](" not in extracted


def test_extract_text_keeps_plain_text_files_unchanged(tmp_path: Path) -> None:
    """
    Markdown 以外のテキストはそのまま返す。
    """
    text_file = tmp_path / "sample.txt"
    text_file.write_text("alpha ![](beta(gamma).png)", encoding="utf-8")

    assert extract_text(text_file) == "alpha ![](beta(gamma).png)"
