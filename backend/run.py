import os

os.environ.setdefault("SEARCH_APP_LAUNCHER_AUTOSTART", "1")

import uvicorn

from app.config import settings


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.bind_host, port=settings.bind_port, reload=False)
