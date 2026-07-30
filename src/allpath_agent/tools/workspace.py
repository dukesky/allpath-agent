from __future__ import annotations

import hashlib
import hmac
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from .registry import ToolDefinition, ToolRegistry, ToolRisk


MAX_READ_BYTES = 100_000
MAX_WRITE_BYTES = 100_000
MAX_SEARCH_FILE_BYTES = 1_000_000
MAX_SEARCH_FILES = 5_000
MAX_SEARCH_RESULTS = 200
DEFAULT_READ_LINES = 400
DEFAULT_SEARCH_RESULTS = 50
SKIPPED_DIRECTORIES = frozenset({".git", ".venv", "venv", "node_modules", "__pycache__"})
SENSITIVE_DIRECTORIES = frozenset({".ssh", ".gnupg"})
SENSITIVE_NAMES = frozenset({"secrets.json", "credentials.json", "id_rsa", "id_ed25519"})
SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".pfx")


class WorkspaceAccessError(ValueError):
    pass


def register_workspace_tools(registry: ToolRegistry, roots: tuple[Path, ...]) -> None:
    workspace = Workspace(roots)
    registry.register(
        ToolDefinition(
            name="read_file",
            description=(
                "Read a UTF-8 text file inside the current workspace. Paths must be relative "
                "and cannot traverse outside the workspace or pass through symbolic links."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "start_line": {"type": "integer"},
                    "max_lines": {"type": "integer"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            handler=workspace.read_file,
        )
    )
    registry.register(
        ToolDefinition(
            name="search_files",
            description=(
                "Search UTF-8 text files inside the current workspace for a literal text query. "
                "Returns matching relative paths, line numbers, and bounded line excerpts."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "minLength": 1},
                    "glob": {"type": "string", "minLength": 1},
                    "max_results": {"type": "integer"},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=workspace.search_files,
        )
    )
    registry.register(
        ToolDefinition(
            name="write_file",
            description=(
                "Create or replace a UTF-8 text file inside the workspace. Replacing an existing "
                "file requires expected_sha256 from a recent read_file result. Requires approval."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "content": {"type": "string"},
                    "expected_sha256": {"type": "string", "minLength": 64},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
            handler=workspace.write_file,
            risk=ToolRisk.SIDE_EFFECT,
        )
    )
    registry.register(
        ToolDefinition(
            name="patch",
            description=(
                "Replace exact text in one UTF-8 workspace file. The old text must occur exactly "
                "expected_occurrences times and expected_sha256 must match. Requires approval."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "minLength": 1},
                    "old_text": {"type": "string", "minLength": 1},
                    "new_text": {"type": "string"},
                    "expected_sha256": {"type": "string", "minLength": 64},
                    "expected_occurrences": {"type": "integer"},
                },
                "required": ["path", "old_text", "new_text", "expected_sha256"],
                "additionalProperties": False,
            },
            handler=workspace.patch,
            risk=ToolRisk.SIDE_EFFECT,
        )
    )


class Workspace:
    def __init__(self, roots: tuple[Path, ...]):
        if not roots:
            raise ValueError("at least one workspace root is required")
        resolved: list[Path] = []
        for root in roots:
            candidate = root.expanduser().resolve(strict=True)
            if not candidate.is_dir():
                raise ValueError(f"workspace root is not a directory: {candidate}")
            if candidate not in resolved:
                resolved.append(candidate)
        self._roots = tuple(resolved)

    def read_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        start_line = arguments.get("start_line", 1)
        max_lines = arguments.get("max_lines", DEFAULT_READ_LINES)
        if start_line < 1:
            raise ValueError("start_line must be positive")
        if max_lines < 1 or max_lines > 2_000:
            raise ValueError("max_lines must be between 1 and 2000")
        root, path, relative = self._resolve_file(arguments["path"])
        data = path.read_bytes()
        if len(data) > MAX_READ_BYTES:
            raise WorkspaceAccessError(
                f"file exceeds the {MAX_READ_BYTES}-byte read limit: {relative}"
            )
        content = _decode_text(data, relative)
        lines = content.splitlines()
        selected = lines[start_line - 1 : start_line - 1 + max_lines]
        end_line = start_line + len(selected) - 1 if selected else start_line - 1
        return {
            "workspace": str(root),
            "path": relative,
            "start_line": start_line,
            "end_line": end_line,
            "total_lines": len(lines),
            "truncated": end_line < len(lines),
            "sha256": _sha256(data),
            "content": "\n".join(selected),
        }

    def search_files(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = arguments["query"]
        pattern = arguments.get("glob", "**/*")
        max_results = arguments.get("max_results", DEFAULT_SEARCH_RESULTS)
        if max_results < 1 or max_results > MAX_SEARCH_RESULTS:
            raise ValueError(f"max_results must be between 1 and {MAX_SEARCH_RESULTS}")
        _validate_glob(pattern)
        lowered_query = query.casefold()
        matches: list[dict[str, Any]] = []
        scanned_files = 0
        skipped_files = 0
        for root in self._roots:
            for path in root.rglob("*"):
                relative_path = path.relative_to(root)
                if any(part in SKIPPED_DIRECTORIES for part in relative_path.parts):
                    continue
                if _is_sensitive(relative_path):
                    skipped_files += 1
                    continue
                if path.is_symlink() or not path.is_file():
                    continue
                relative = relative_path.as_posix()
                if pattern != "**/*" and not PurePosixPath(relative).match(pattern):
                    continue
                scanned_files += 1
                if scanned_files > MAX_SEARCH_FILES:
                    return _search_result(matches, scanned_files - 1, skipped_files, True)
                try:
                    if path.stat().st_size > MAX_SEARCH_FILE_BYTES:
                        skipped_files += 1
                        continue
                    content = _decode_text(path.read_bytes(), relative)
                except (OSError, WorkspaceAccessError):
                    skipped_files += 1
                    continue
                for line_number, line in enumerate(content.splitlines(), 1):
                    if lowered_query in line.casefold():
                        matches.append(
                            {
                                "workspace": str(root),
                                "path": relative,
                                "line": line_number,
                                "text": line[:500],
                            }
                        )
                        if len(matches) >= max_results:
                            return _search_result(matches, scanned_files, skipped_files, True)
        return _search_result(matches, scanned_files, skipped_files, False)

    def write_file(self, arguments: dict[str, Any]) -> dict[str, Any]:
        root, path, relative, existed = self._resolve_write_target(arguments["path"])
        content = arguments["content"]
        data = content.encode("utf-8")
        if len(data) > MAX_WRITE_BYTES:
            raise WorkspaceAccessError(
                f"content exceeds the {MAX_WRITE_BYTES}-byte write limit: {relative}"
            )
        previous_sha256 = None
        if existed:
            previous = path.read_bytes()
            if len(previous) > MAX_READ_BYTES:
                raise WorkspaceAccessError(
                    f"existing file exceeds the {MAX_READ_BYTES}-byte mutation limit: {relative}"
                )
            _decode_text(previous, relative)
            previous_sha256 = _sha256(previous)
            expected = arguments.get("expected_sha256")
            if expected is None:
                raise WorkspaceAccessError(
                    "expected_sha256 is required when replacing an existing file"
                )
            _require_sha256(expected, previous_sha256)
        elif arguments.get("expected_sha256") is not None:
            raise WorkspaceAccessError("expected_sha256 cannot be used when creating a new file")
        _atomic_write(path, data)
        return {
            "workspace": str(root),
            "path": relative,
            "created": not existed,
            "bytes_written": len(data),
            "previous_sha256": previous_sha256,
            "sha256": _sha256(data),
        }

    def patch(self, arguments: dict[str, Any]) -> dict[str, Any]:
        root, path, relative = self._resolve_file(arguments["path"])
        data = path.read_bytes()
        if len(data) > MAX_READ_BYTES:
            raise WorkspaceAccessError(
                f"file exceeds the {MAX_READ_BYTES}-byte mutation limit: {relative}"
            )
        content = _decode_text(data, relative)
        current_sha256 = _sha256(data)
        _require_sha256(arguments["expected_sha256"], current_sha256)
        old_text = arguments["old_text"]
        new_text = arguments["new_text"]
        expected_occurrences = arguments.get("expected_occurrences", 1)
        if expected_occurrences < 1 or expected_occurrences > 100:
            raise ValueError("expected_occurrences must be between 1 and 100")
        occurrence_count = content.count(old_text)
        if occurrence_count != expected_occurrences:
            raise WorkspaceAccessError(
                f"old_text occurrence mismatch: expected {expected_occurrences}, found {occurrence_count}"
            )
        updated = content.replace(old_text, new_text)
        updated_data = updated.encode("utf-8")
        if len(updated_data) > MAX_WRITE_BYTES:
            raise WorkspaceAccessError(
                f"patched content exceeds the {MAX_WRITE_BYTES}-byte write limit: {relative}"
            )
        _atomic_write(path, updated_data)
        return {
            "workspace": str(root),
            "path": relative,
            "replacements": occurrence_count,
            "bytes_written": len(updated_data),
            "previous_sha256": current_sha256,
            "sha256": _sha256(updated_data),
        }

    def _resolve_file(self, raw_path: str) -> tuple[Path, Path, str]:
        relative_path = _relative_path(raw_path)
        if _is_sensitive(relative_path):
            raise WorkspaceAccessError("sensitive credential files are not available to tools")
        for root in self._roots:
            candidate = root.joinpath(*relative_path.parts)
            if not candidate.exists():
                continue
            _reject_symlinks(root, relative_path)
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(root):
                raise WorkspaceAccessError("path resolves outside the workspace")
            if not resolved.is_file():
                raise WorkspaceAccessError(f"path is not a file: {relative_path.as_posix()}")
            return root, resolved, relative_path.as_posix()
        raise FileNotFoundError(f"workspace file does not exist: {relative_path.as_posix()}")

    def _resolve_write_target(self, raw_path: str) -> tuple[Path, Path, str, bool]:
        relative_path = _relative_path(raw_path)
        if _is_sensitive(relative_path):
            raise WorkspaceAccessError("sensitive credential files are not available to tools")
        for root in self._roots:
            candidate = root.joinpath(*relative_path.parts)
            parent = candidate.parent
            if not parent.exists():
                continue
            _reject_symlinks(root, relative_path)
            resolved_parent = parent.resolve(strict=True)
            if not resolved_parent.is_relative_to(root):
                raise WorkspaceAccessError("path resolves outside the workspace")
            if not resolved_parent.is_dir():
                raise WorkspaceAccessError(f"parent is not a directory: {relative_path.parent}")
            if candidate.exists() and not candidate.is_file():
                raise WorkspaceAccessError(f"path is not a file: {relative_path.as_posix()}")
            return root, candidate, relative_path.as_posix(), candidate.exists()
        raise FileNotFoundError(
            f"workspace parent directory does not exist: {relative_path.parent.as_posix()}"
        )


def _relative_path(raw_path: str) -> PurePosixPath:
    normalized = raw_path.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or not path.parts:
        raise WorkspaceAccessError("workspace paths must be relative")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise WorkspaceAccessError("workspace paths cannot contain traversal components")
    return path


def _validate_glob(pattern: str) -> None:
    normalized = pattern.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise WorkspaceAccessError("glob must stay inside the workspace")


def _is_sensitive(path: PurePosixPath) -> bool:
    lowered_parts = tuple(part.casefold() for part in path.parts)
    name = lowered_parts[-1]
    return (
        any(part in SENSITIVE_DIRECTORIES for part in lowered_parts)
        or name == ".env"
        or name.startswith(".env.")
        or name in SENSITIVE_NAMES
        or name.endswith(SENSITIVE_SUFFIXES)
    )


def _reject_symlinks(root: Path, relative: PurePosixPath) -> None:
    candidate = root
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise WorkspaceAccessError("workspace paths cannot pass through symbolic links")


def _decode_text(data: bytes, relative: str) -> str:
    if b"\x00" in data[:8192]:
        raise WorkspaceAccessError(f"binary file is not readable as text: {relative}")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise WorkspaceAccessError(f"file is not valid UTF-8 text: {relative}") from error


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _require_sha256(expected: str, actual: str) -> None:
    if len(expected) != 64 or any(character not in "0123456789abcdefABCDEF" for character in expected):
        raise WorkspaceAccessError("expected_sha256 must be a 64-character hexadecimal digest")
    if not hmac.compare_digest(expected.casefold(), actual):
        raise WorkspaceAccessError("file changed since it was read; read it again before writing")


def _atomic_write(path: Path, data: bytes) -> None:
    temporary_path: Path | None = None
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    try:
        descriptor, raw_temporary_path = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".allpath-tmp",
            dir=path.parent,
        )
        temporary_path = Path(raw_temporary_path)
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
        temporary_path = None
        try:
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except OSError:
            pass
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _search_result(
    matches: list[dict[str, Any]],
    scanned_files: int,
    skipped_files: int,
    truncated: bool,
) -> dict[str, Any]:
    return {
        "matches": matches,
        "match_count": len(matches),
        "scanned_files": scanned_files,
        "skipped_files": skipped_files,
        "truncated": truncated,
    }
