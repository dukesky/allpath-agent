from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence


LABEL = "ai.allpath.gateway"
Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class GatewayServiceStatus:
    installed: bool
    running: bool
    detail: str


class GatewayServiceManager:
    def __init__(
        self,
        allpath_home: Path,
        *,
        platform_name: str | None = None,
        user_home: Path | None = None,
        executable: str | None = None,
        runner: Runner | None = None,
        user_id: int | None = None,
    ):
        self.allpath_home = allpath_home.expanduser().resolve()
        self.platform_name = platform_name or sys.platform
        self.user_home = (user_home or Path.home()).expanduser()
        self.executable = executable or shutil.which("allpath-agent") or sys.argv[0]
        self._runner = runner or _run
        self.user_id = os.getuid() if user_id is None else user_id

    @property
    def service_path(self) -> Path:
        if self.platform_name == "darwin":
            return self.user_home / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        if self.platform_name.startswith("linux"):
            return self.user_home / ".config" / "systemd" / "user" / "allpath-agent-gateway.service"
        raise RuntimeError("Background gateway service is supported on macOS and Linux")

    def install(self) -> GatewayServiceStatus:
        path = self.service_path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.allpath_home.mkdir(parents=True, exist_ok=True)
        (self.allpath_home / "logs").mkdir(parents=True, exist_ok=True)
        if self.platform_name == "darwin":
            path.write_bytes(plistlib.dumps(self._launch_agent_payload()))
            domain = f"gui/{self.user_id}"
            self._runner(("launchctl", "bootout", domain, str(path)))
            result = self._runner(("launchctl", "bootstrap", domain, str(path)))
        else:
            path.write_text(self._systemd_unit(), encoding="utf-8")
            self._runner(("systemctl", "--user", "daemon-reload"))
            result = self._runner(("systemctl", "--user", "enable", "--now", "allpath-agent-gateway.service"))
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "could not start gateway service")
        return self.status()

    def status(self) -> GatewayServiceStatus:
        path = self.service_path
        if not path.is_file():
            return GatewayServiceStatus(False, False, f"not installed: {path}")
        if self.platform_name == "darwin":
            result = self._runner(("launchctl", "print", f"gui/{self.user_id}/{LABEL}"))
        else:
            result = self._runner(("systemctl", "--user", "is-active", "allpath-agent-gateway.service"))
        running = result.returncode == 0
        detail = "running" if running else (result.stderr.strip() or result.stdout.strip() or "stopped")
        return GatewayServiceStatus(True, running, detail)

    def restart(self) -> GatewayServiceStatus:
        if not self.service_path.is_file():
            raise RuntimeError("gateway service is not installed")
        if self.platform_name == "darwin":
            result = self._runner(("launchctl", "kickstart", "-k", f"gui/{self.user_id}/{LABEL}"))
        else:
            result = self._runner(("systemctl", "--user", "restart", "allpath-agent-gateway.service"))
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or "could not restart gateway service")
        return self.status()

    def uninstall(self) -> GatewayServiceStatus:
        path = self.service_path
        if self.platform_name == "darwin":
            self._runner(("launchctl", "bootout", f"gui/{self.user_id}", str(path)))
        else:
            self._runner(("systemctl", "--user", "disable", "--now", "allpath-agent-gateway.service"))
        path.unlink(missing_ok=True)
        if self.platform_name.startswith("linux"):
            self._runner(("systemctl", "--user", "daemon-reload"))
        return GatewayServiceStatus(False, False, "uninstalled")

    def _launch_agent_payload(self) -> dict:
        logs = self.allpath_home / "logs"
        return {
            "Label": LABEL,
            "ProgramArguments": [self.executable, "--home", str(self.allpath_home), "gateway"],
            "RunAtLoad": True,
            "KeepAlive": True,
            "ProcessType": "Background",
            "StandardOutPath": str(logs / "gateway.out.log"),
            "StandardErrorPath": str(logs / "gateway.error.log"),
        }

    def _systemd_unit(self) -> str:
        logs = self.allpath_home / "logs"
        return "\n".join(
            (
                "[Unit]",
                "Description=Allpath Agent messaging gateway",
                "After=network-online.target",
                "",
                "[Service]",
                f'ExecStart="{self.executable}" --home "{self.allpath_home}" gateway',
                "Restart=on-failure",
                "RestartSec=5",
                f'StandardOutput=append:{logs / "gateway.out.log"}',
                f'StandardError=append:{logs / "gateway.error.log"}',
                "",
                "[Install]",
                "WantedBy=default.target",
                "",
            )
        )


def _run(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)
