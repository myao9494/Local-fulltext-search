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
    # Avoid locale-sensitive AppleScript keywords by using JXA.
    # `chooseFolder` (Standard Additions) is more stable than manual NSOpenPanel wiring.
    script = (
        "const app = Application.currentApplication(); "
        "app.includeStandardAdditions = true; "
        "app.activate(); "
        "const selected = app.chooseFolder({ withPrompt: '検索対象フォルダを選択' }); "
        "selected.toString();"
    )
    result = subprocess.run(
        ["/usr/bin/osascript", "-l", "JavaScript", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip()
        stderr_lower = stderr.lower()
        # osascript uses error code -128 when the user cancels the dialog.
        if "cancel" in stderr_lower or "キャンセル" in stderr or "(-128)" in stderr:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Folder selection was cancelled.")
        detail = "macOS folder dialog failed to open."
        if stderr:
            detail = f"{detail} ({stderr[:200]})"
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=detail)
    selected = result.stdout.strip()
    if not selected:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Folder selection was cancelled.")
    return selected


def _pick_folder_windows() -> str:
    # 一時的な最前面フォームを親にしてダイアログを開き、
    # ブラウザや他ウィンドウの背後へ回り込みにくくする。
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        "$owner = New-Object System.Windows.Forms.Form; "
        "$owner.Text = 'FolderPickerOwner'; "
        "$owner.ShowInTaskbar = $false; "
        "$owner.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedToolWindow; "
        "$owner.StartPosition = [System.Windows.Forms.FormStartPosition]::Manual; "
        "$owner.Location = New-Object System.Drawing.Point(-32000, -32000); "
        "$owner.Size = New-Object System.Drawing.Size(1, 1); "
        "$owner.Opacity = 0; "
        "$owner.TopMost = $true; "
        "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
        "$dialog.Description = '検索対象フォルダを選択'; "
        "$dialog.ShowNewFolderButton = $false; "
        "try { "
        "$owner.Show(); "
        "$owner.Activate(); "
        "$owner.BringToFront(); "
        "if ($dialog.ShowDialog($owner) -eq [System.Windows.Forms.DialogResult]::OK) { "
        "[Console]::Write($dialog.SelectedPath) } "
        "} finally { "
        "$dialog.Dispose(); "
        "$owner.Close(); "
        "$owner.Dispose(); "
        "}"
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
