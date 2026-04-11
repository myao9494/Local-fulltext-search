from pathlib import Path


def normalize_path(raw_path: str | Path) -> Path:
    return Path(raw_path).expanduser().resolve()


def normalize_path_str(raw_path: str | Path) -> str:
    return normalize_path(raw_path).as_posix()


def get_relative_path(root_path: Path, target_path: Path) -> Path:
    return target_path.relative_to(root_path)


def get_depth(relative_path: Path) -> int:
    return len(relative_path.parts) - 1
