from __future__ import annotations

import json
import os
from pathlib import Path


FALLBACK_MODELS: dict[str, tuple[str, ...]] = {
    "openai": ("gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex"),
    "openai-codex": ("gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex"),
    "anthropic": ("claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"),
    "openrouter": ("openai/gpt-5.4", "anthropic/claude-sonnet-4.6"),
    "ollama": ("llama3.2",),
    "claude-code": ("sonnet", "opus", "haiku"),
}


def available_models(provider_id: str) -> tuple[str, ...]:
    if provider_id == "openai-codex":
        discovered = _codex_cached_models()
        if discovered:
            return discovered
    return FALLBACK_MODELS.get(provider_id, ())


def _codex_cached_models() -> tuple[str, ...]:
    codex_home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
    cache_path = codex_home / "models_cache.json"
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    entries = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return ()
    ranked: list[tuple[int, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        slug = entry.get("slug")
        if not isinstance(slug, str) or not slug.strip():
            continue
        if str(entry.get("visibility", "")).lower() in {"hide", "hidden"}:
            continue
        priority = entry.get("priority")
        ranked.append((int(priority) if isinstance(priority, (int, float)) else 10_000, slug.strip()))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return tuple(dict.fromkeys(slug for _, slug in ranked))
