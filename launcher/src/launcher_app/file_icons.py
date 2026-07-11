"""検索結果へ Catppuccin のファイル種別アイコンを割り当てる。"""

from __future__ import annotations

from pathlib import Path

from launcher_app.models import SearchResultItem


def catppuccin_icon_name(item: SearchResultItem) -> str:
    """検索結果の種別と拡張子から Catppuccin SVG 名を返す。"""
    if item.source_type == "gantt":
        return "task.svg"
    if item.source_type == "web":
        return "html.svg"
    if item.result_kind == "folder":
        return "folder.svg"

    extension = Path(item.file_name).suffix.lower().lstrip(".")
    icon_by_extension = {
        "md": "markdown.svg", "markdown": "markdown.svg", "pdf": "pdf.svg", "json": "json.svg", "xml": "xml.svg",
        "txt": "txt.svg", "csv": "csv.svg", "yaml": "yaml.svg", "yml": "yaml.svg", "zip": "zip.svg",
        "html": "html.svg", "htm": "html.svg", "js": "javascript.svg", "jsx": "javascript.svg",
        "ts": "typescript.svg", "tsx": "typescript.svg", "py": "python.svg",
        "excalidraw": "excalidraw.svg", "dio": "drawio.svg", "drawio": "drawio.svg", "epub": "epub.svg",
        "png": "image.svg", "jpg": "image.svg", "jpeg": "image.svg", "gif": "image.svg", "svg": "image.svg", "webp": "image.svg",
        "mp3": "audio.svg", "wav": "audio.svg", "m4a": "audio.svg", "mp4": "video.svg", "mov": "video.svg", "avi": "video.svg",
    }
    return icon_by_extension.get(extension, "file.svg")


def catppuccin_icon_path(item: SearchResultItem) -> Path:
    """ネイティブ macOS UI が直接読み込める SVG の絶対パスを返す。"""
    return Path(__file__).parent / "assets" / "catppuccin" / catppuccin_icon_name(item)
