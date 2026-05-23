"""
ランチャーのメモ入力から gantt タスク作成 API の payload を組み立てる。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def build_gantt_task_payload(title: str, memo: str, *, parent: int = 0, today: date | None = None) -> dict[str, Any]:
    """
    タスク名とメモから gantt のタスク作成 payload へ変換する。
    """
    base_date = today or date.today()
    end_date = base_date + timedelta(days=1)
    return {
        "text": title.strip(),
        "start_date": f"{base_date.isoformat()} 00:00:00",
        "end_date": f"{end_date.isoformat()} 00:00:00",
        "progress": 0.1,
        "parent": parent,
        "kind_task": 1,
        "memo": memo.strip(),
    }


def normalize_parent_id(value: object, *, default: int = 0) -> int:
    """
    UI 入力の parent ID を gantt API に渡せる 0 以上の整数へ正規化する。
    """
    try:
        parent = int(str(value).strip())
    except (TypeError, ValueError):
        return default
    return parent if parent >= 0 else default
