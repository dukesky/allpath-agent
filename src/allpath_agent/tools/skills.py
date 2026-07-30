from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .registry import ToolDefinition, ToolRegistry
from .workspace import WorkspaceAccessError


MAX_SKILL_FILE_BYTES = 100_000
SKILL_NAME = re.compile(r"^[a-z][a-z0-9-]{0,63}$")


@dataclass(frozen=True)
class SkillRecord:
    name: str
    description: str
    directory: Path
    source: str


def default_skill_roots(home: Path, workspace: Path) -> tuple[tuple[Path, str], ...]:
    return (
        (Path(__file__).resolve().parents[1] / "builtin_skills", "builtin"),
        (home / "skills", "user"),
        (workspace / ".allpath" / "skills", "project"),
    )


def register_skill_tools(
    registry: ToolRegistry,
    roots: tuple[tuple[Path, str], ...],
) -> None:
    catalog = SkillCatalog(roots)
    registry.register(
        ToolDefinition(
            name="skills_list",
            description="List available Allpath Skills using metadata only.",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=lambda arguments: {"skills": catalog.list_metadata()},
        )
    )
    registry.register(
        ToolDefinition(
            name="skill_view",
            description=(
                "Load one Skill's full SKILL.md instructions or one supporting file on demand."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "minLength": 1},
                    "file_path": {"type": "string", "minLength": 1},
                },
                "required": ["name"],
                "additionalProperties": False,
            },
            handler=lambda arguments: catalog.view(
                arguments["name"], arguments.get("file_path", "SKILL.md")
            ),
        )
    )


class SkillCatalog:
    def __init__(self, roots: tuple[tuple[Path, str], ...]):
        self._roots = roots

    def scan(self) -> dict[str, SkillRecord]:
        records: dict[str, SkillRecord] = {}
        for raw_root, source in self._roots:
            root = raw_root.expanduser()
            if not root.is_dir() or root.is_symlink():
                continue
            for skill_file in sorted(root.rglob("SKILL.md")):
                if skill_file.is_symlink() or not skill_file.is_file():
                    continue
                relative_skill_file = skill_file.relative_to(root)
                current = root
                contains_symlink = False
                for part in relative_skill_file.parts:
                    current = current / part
                    if current.is_symlink():
                        contains_symlink = True
                        break
                if contains_symlink:
                    continue
                try:
                    content = _read_skill_text(skill_file)
                    metadata = _frontmatter(content)
                    name = metadata["name"]
                    description = metadata["description"]
                except (KeyError, OSError, ValueError, WorkspaceAccessError):
                    continue
                if not SKILL_NAME.fullmatch(name):
                    continue
                records[name] = SkillRecord(name, description, skill_file.parent, source)
        return records

    def list_metadata(self) -> list[dict[str, str]]:
        return [
            {
                "name": record.name,
                "description": record.description,
                "source": record.source,
            }
            for record in sorted(self.scan().values(), key=lambda item: item.name)
        ]

    def view(self, name: str, file_path: str = "SKILL.md") -> dict[str, Any]:
        record = self.scan().get(name)
        if record is None:
            raise KeyError(f"unknown skill: {name}")
        relative = _skill_relative_path(file_path)
        candidate = record.directory.joinpath(*relative.parts)
        current = record.directory
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise WorkspaceAccessError("skill files cannot pass through symbolic links")
        resolved = candidate.resolve(strict=True)
        directory = record.directory.resolve(strict=True)
        if not resolved.is_relative_to(directory) or not resolved.is_file():
            raise WorkspaceAccessError("skill file must stay inside its skill directory")
        return {
            "name": record.name,
            "description": record.description,
            "source": record.source,
            "directory": str(directory),
            "file_path": relative.as_posix(),
            "content": _read_skill_text(resolved),
        }

    def expand_invocation(self, message: str) -> str | None:
        command, separator, instruction = message.partition(" ")
        if not command.startswith("/"):
            return None
        name = command[1:]
        if name not in self.scan():
            return None
        loaded = self.view(name)
        user_instruction = instruction.strip() if separator else ""
        parts = [
            f"[The user explicitly invoked the Allpath Skill `{name}`. Follow it for this task.]",
            "",
            loaded["content"],
            "",
            f"[Skill directory: {loaded['directory']}]",
            "Resolve relative references, templates, and scripts against this directory. "
            "Use only currently available Allpath tools and preserve all approval boundaries.",
        ]
        if user_instruction:
            parts.extend(("", f"User instruction: {user_instruction}"))
        return "\n".join(parts)


def _frontmatter(content: str) -> dict[str, str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("SKILL.md requires YAML frontmatter")
    metadata: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, separator, value = line.partition(":")
        if separator and key.strip() in {"name", "description"}:
            metadata[key.strip()] = value.strip().strip('"\'')
    if not metadata.get("name") or not metadata.get("description"):
        raise ValueError("SKILL.md requires name and description")
    if len(metadata["description"]) > 1_024:
        raise ValueError("skill description is too long")
    return metadata


def _skill_relative_path(raw_path: str) -> PurePosixPath:
    path = PurePosixPath(raw_path.replace("\\", "/"))
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise WorkspaceAccessError("skill file paths must be safe relative paths")
    return path


def _read_skill_text(path: Path) -> str:
    data = path.read_bytes()
    if len(data) > MAX_SKILL_FILE_BYTES:
        raise WorkspaceAccessError("skill file exceeds the read limit")
    if b"\x00" in data[:8192]:
        raise WorkspaceAccessError("binary skill files are not supported")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise WorkspaceAccessError("skill file is not valid UTF-8") from error
