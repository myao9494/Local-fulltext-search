from datetime import datetime

from pydantic import BaseModel


class IndexRunRequest(BaseModel):
    folder_id: int | None = None


class IndexStatusResponse(BaseModel):
    last_started_at: datetime | None
    last_finished_at: datetime | None
    total_files: int
    error_count: int
    is_running: bool
    last_error: str | None
