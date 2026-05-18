"""
ランチャーのメモ入力から gantt タスク作成 API の payload を組み立てる。
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def build_gantt_task_payload(raw_text: str, *, parent: int = 0, today: date | None = None) -> dict[str, Any]:
    """
    1行目をタスク名、2行目以降をメモとして gantt のタスク作成 payload へ変換する。
    """
    lines = raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    title = lines[0].strip() if lines else ""
    memo = "\n".join(lines[1:]).strip()
    base_date = today or date.today()
    end_date = base_date + timedelta(days=1)
    return {
        "text": title,
        "start_date": f"{base_date.isoformat()} 00:00:00",
        "end_date": f"{end_date.isoformat()} 00:00:00",
        "progress": 0.1,
        "parent": parent,
        "kind_task": 1,
        "memo": memo,
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
