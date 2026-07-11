from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Mapping


class SecretStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser()

    def values(self) -> dict[str, str]:
        if not self.path.is_file():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"could not read secret store: {error}") from error
        if not isinstance(payload, dict):
            raise ValueError("secret store must contain a JSON object")
        return {
            key: value
            for key, value in payload.items()
            if isinstance(key, str) and isinstance(value, str) and value
        }

    def set(self, key: str, value: str) -> None:
        if not key.strip() or not value:
            raise ValueError("secret key and value cannot be empty")
        values = self.values()
        values[key] = value
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(
            json.dumps(values, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        os.chmod(temporary, 0o600)
        temporary.replace(self.path)
        os.chmod(self.path, 0o600)

    def merged_environment(
        self,
        base: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        environment = dict(base if base is not None else os.environ)
        environment.update(self.values())
        return environment
