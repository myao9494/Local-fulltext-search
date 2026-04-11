import platform
import subprocess

from fastapi import APIRouter, HTTPException, status

router = APIRouter(prefix="/api/folders", tags=["folders"])


@router.post("/pick")
def pick_folder() -> dict[str, str]:
    system_name = platform.system()
    if system_name == "Darwin":
        return {"full_path": _pick_folder_macos()}
    if system_name == "Windows":
        return {"full_path": _pick_folder_windows()}
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail="Native folder dialog is supported only on macOS and Windows in Phase 1.",
    )


def _pick_folder_macos() -> str:
    result = subprocess.run(
        ["/usr/bin/osascript", "-e", 'POSIX path of (choose folder with prompt "検索対象フォルダを選択")'],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip().lower()
        if "cancel" in stderr:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Folder selection was cancelled.")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="macOS folder dialog failed to open.")
    selected = result.stdout.strip()
    if not selected:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Folder selection was cancelled.")
    return selected


def _pick_folder_windows() -> str:
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$dialog.Description = '検索対象フォルダを選択'; "
        "$dialog.ShowNewFolderButton = $false; "
        "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { "
        "[Console]::Write($dialog.SelectedPath) }"
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Windows folder dialog failed to open.")
    selected = result.stdout.strip()
    if not selected:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Folder selection was cancelled.")
    return selected
