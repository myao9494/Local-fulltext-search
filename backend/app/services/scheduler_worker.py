"""
スケジューラー子プロセスのエントリポイント。
"""

from __future__ import annotations

import sys

from app.db.connection import get_connection
from app.db.schema import initialize_schema
from app.services.scheduler_service import SchedulerService


def main() -> int:
    """
    引数で受けた run_token のジョブだけを実行する。
    """
    if len(sys.argv) < 2:
        raise SystemExit("run_token is required")

    connection = get_connection()
    try:
        initialize_schema(connection)
        SchedulerService(connection=connection).run_scheduled_indexing(run_token=sys.argv[1])
    finally:
        connection.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
