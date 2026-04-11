from pathlib import Path


SUPPORTED_EXTENSIONS: set[str] = {".md", ".json", ".txt"}


def supports_extension(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def extract_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")
