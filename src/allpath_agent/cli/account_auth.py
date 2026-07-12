from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def ensure_codex_login(command: str | None = None) -> tuple[bool, str, str]:
    resolved = command or resolve_codex_command()
    if not resolved:
        return False, "Codex CLI is not installed. Install it, then retry.", ""
    status = subprocess.run(
        [resolved, "login", "status"],
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    if status.returncode == 0:
        return True, "OpenAI Codex account is already signed in.", resolved
    login = subprocess.run([resolved, "login"], check=False)
    if login.returncode != 0:
        return False, "OpenAI Codex login was cancelled or failed.", resolved
    return True, "OpenAI Codex account connected.", resolved


def resolve_codex_command() -> str:
    candidates: list[str] = []
    path_command = shutil.which("codex")
    if path_command:
        candidates.append(path_command)
    app_command = Path("/Applications/ChatGPT.app/Contents/Resources/codex")
    if app_command.is_file():
        candidates.append(str(app_command))
    ranked = sorted(
        ((_codex_version(candidate), candidate) for candidate in dict.fromkeys(candidates)),
        reverse=True,
    )
    return ranked[0][1] if ranked else ""


def _codex_version(command: str) -> tuple[int, ...]:
    try:
        result = subprocess.run(
            [command, "--version"],
            text=True,
            capture_output=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ()
    version = result.stdout.strip().split()[-1] if result.stdout.strip() else ""
    try:
        return tuple(int(part) for part in version.split("-", 1)[0].split("."))
    except ValueError:
        return ()
