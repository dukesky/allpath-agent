from __future__ import annotations

import shutil
import subprocess


def ensure_codex_login(command: str = "codex") -> tuple[bool, str]:
    if not shutil.which(command):
        return False, "Codex CLI is not installed. Install it, then retry OpenAI account connection."
    status = subprocess.run(
        [command, "login", "status"],
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    if status.returncode == 0:
        return True, "OpenAI Codex account is already signed in."
    login = subprocess.run([command, "login"], check=False)
    if login.returncode != 0:
        return False, "OpenAI Codex login was cancelled or failed."
    return True, "OpenAI Codex account connected."
