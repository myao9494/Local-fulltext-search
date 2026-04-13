"""
Markdown 抽出の整形ルールを検証する。
画像リンクや通常リンクを平文化し、Office/PDF/Outlook も検索用テキストへ変換できることを担保する。
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app.extractors.text_extractor import extract_text, supports_extension


def test_supports_extension_includes_office_pdf_and_images() -> None:
    """
    対応拡張子には Office/PDF/Outlook と画像のファイル名検索対象が含まれる。
    """
    assert supports_extension(Path("report.docx")) is True
    assert supports_extension(Path("sheet.xlsx")) is True
    assert supports_extension(Path("deck.pptx")) is True
    assert supports_extension(Path("memo.pdf")) is True
    assert supports_extension(Path("mail.msg")) is True
    assert supports_extension(Path("photo.png")) is True
    assert supports_extension(Path("archive.zip")) is False


def test_extract_text_reads_docx_paragraphs_and_tables(tmp_path: Path) -> None:
    """
    DOCX は本文段落と表セルを検索用テキストとして抽出する。
    """
    from docx import Document

    document = Document()
    document.add_heading("週次レポート")
    document.add_paragraph("営業進捗を確認する")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "担当"
    table.cell(0, 1).text = "件数"
    table.cell(1, 0).text = "田中"
    table.cell(1, 1).text = "12"
    docx_file = tmp_path / "report.docx"
    document.save(docx_file)

    extracted = extract_text(docx_file)

    assert "週次レポート" in extracted
    assert "営業進捗を確認する" in extracted
    assert "担当\t件数" in extracted
    assert "田中\t12" in extracted


def test_extract_text_reads_xlsx_sheet_names_and_cell_values(tmp_path: Path) -> None:
    """
    XLSX はシート名とセル値を検索用テキストとして抽出する。
    """
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "売上"
    sheet["A1"] = "担当"
    sheet["B1"] = "金額"
    sheet["A2"] = "佐藤"
    sheet["B2"] = 125000
    xlsx_file = tmp_path / "sales.xlsx"
    workbook.save(xlsx_file)

    extracted = extract_text(xlsx_file)

    assert "[Sheet] 売上" in extracted
    assert "担当\t金額" in extracted
    assert "佐藤\t125000" in extracted


def test_extract_text_reads_pptx_slide_text(tmp_path: Path) -> None:
    """
    PPTX は各スライドのテキストを検索用テキストとして抽出する。
    """
    from pptx import Presentation

    presentation = Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[1])
    slide.shapes.title.text = "検索基盤"
    slide.placeholders[1].text = "並列抽出を導入する"
    pptx_file = tmp_path / "plan.pptx"
    presentation.save(pptx_file)

    extracted = extract_text(pptx_file)

    assert "[Slide 1]" in extracted
    assert "検索基盤" in extracted
    assert "並列抽出を導入する" in extracted


def test_extract_text_reads_pdf_text_via_pypdf(tmp_path: Path) -> None:
    """
    PDF は各ページの抽出結果を連結して検索用テキストへ変換する。
    """
    pdf_file = tmp_path / "memo.pdf"
    pdf_file.write_bytes(b"%PDF-1.4")

    class FakePage:
        def __init__(self, text: str) -> None:
            self._text = text

        def extract_text(self, *args, **kwargs) -> str:
            return self._text

    class FakePdfReader:
        def __init__(self, *args, **kwargs) -> None:
            self.pages = [FakePage("1ページ目"), FakePage("2ページ目")]

    with patch.dict("sys.modules", {"pypdf": SimpleNamespace(PdfReader=FakePdfReader)}):
        extracted = extract_text(pdf_file)

    assert "[Page 1]" in extracted
    assert "1ページ目" in extracted
    assert "2ページ目" in extracted


def test_extract_text_reads_msg_header_and_body(tmp_path: Path) -> None:
    """
    Outlook の MSG は件名や差出人と本文を検索用テキストへ変換する。
    """
    msg_file = tmp_path / "mail.msg"
    msg_file.write_bytes(b"msg")

    class FakeMessage:
        subject = "見積確認"
        sender = "sales@example.com"
        to = "team@example.com"
        cc = None
        date = "2026-04-13 10:30:00"
        body = "案件の見積を確認してください。"

        def close(self) -> None:
            return None

    def fake_open_msg(path: str, **kwargs) -> FakeMessage:
        assert path.endswith("mail.msg")
        return FakeMessage()

    with patch.dict("sys.modules", {"extract_msg": SimpleNamespace(openMsg=fake_open_msg)}):
        extracted = extract_text(msg_file)

    assert "Subject: 見積確認" in extracted
    assert "From: sales@example.com" in extracted
    assert "To: team@example.com" in extracted
    assert "案件の見積を確認してください。" in extracted


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
