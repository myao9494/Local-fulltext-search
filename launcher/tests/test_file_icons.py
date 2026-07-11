"""ランチャーの Catppuccin アイコン選択規則を検証する。"""

from launcher_app.file_icons import catppuccin_icon_name
from launcher_app.models import SearchResultItem


def test_catppuccin_icon_name_uses_result_kind_source_and_extension() -> None:
    """フォルダ・gantt・代表的な拡張子が専用アイコンになる。"""
    assert catppuccin_icon_name(_item("notes.md")) == "markdown.svg"
    assert catppuccin_icon_name(_item("report.pdf")) == "pdf.svg"
    assert catppuccin_icon_name(_item("diagram.excalidraw")) == "excalidraw.svg"
    assert catppuccin_icon_name(_item("records", result_kind="folder")) == "folder.svg"
    assert catppuccin_icon_name(_item("task", source_type="gantt")) == "task.svg"
    assert catppuccin_icon_name(_item("page", source_type="web")) == "html.svg"


def _item(file_name: str, *, result_kind: str = "file", source_type: str = "local") -> SearchResultItem:
    """アイコン判定専用の最小検索結果を作る。"""
    return SearchResultItem(
        file_id=1,
        result_kind=result_kind,
        source_type=source_type,
        target_path="/tmp",
        file_name=file_name,
        full_path=f"/tmp/{file_name}",
        file_ext=file_name.rsplit(".", 1)[-1] if "." in file_name else "",
        snippet="",
        created_at="",
        mtime="",
        click_count=0,
    )
