"""
ランチャーメモから gantt タスク作成 payload を組み立てる仕様を検証する。
"""

from datetime import date

from launcher_app.gantt_task import build_gantt_task_payload, normalize_parent_id


def test_build_gantt_task_payload_splits_first_line_and_memo() -> None:
    """
    タスク名とメモを指定して、開始日は今日、終了日は明日にする。
    """
    payload = build_gantt_task_payload(
        "AI テストタスク",
        "API ガイドから作成したメモ\n2行目",
        parent=12,
        today=date(2026, 5, 18),
    )

    assert payload == {
        "text": "AI テストタスク",
        "start_date": "2026-05-18 00:00:00",
        "end_date": "2026-05-19 00:00:00",
        "progress": 0.1,
        "parent": 12,
        "kind_task": 1,
        "memo": "API ガイドから作成したメモ\n2行目",
    }



def test_normalize_parent_id_accepts_non_negative_integer_text() -> None:
    """
    ハンバーガーメニューの parent 入力は 0 以上の整数だけを採用する。
    """
    assert normalize_parent_id(" 42 ") == 42
    assert normalize_parent_id("-1", default=7) == 7
    assert normalize_parent_id("abc", default=7) == 7
