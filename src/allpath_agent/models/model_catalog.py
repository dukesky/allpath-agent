from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


FALLBACK_MODELS: dict[str, tuple[str, ...]] = {
    "openai": ("gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex"),
    "openai-codex": ("gpt-5.4", "gpt-5.4-mini", "gpt-5.3-codex"),
    "anthropic": ("claude-opus-4-6", "claude-sonnet-4-6", "claude-haiku-4-5"),
    "xai": ("grok-4.20", "grok-4.1-fast", "grok-4"),
    "gemini": ("gemini-3.5-pro", "gemini-3.5-flash", "gemini-3-flash"),
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


def discover_provider_models(
    provider_id: str,
    base_url: str,
    api_key: str,
    timeout_seconds: float = 15,
) -> tuple[str, ...]:
    try:
        if provider_id == "gemini":
            payload = _get_json(
                f"{base_url.rstrip('/')}/models?{urlencode({'key': api_key, 'pageSize': 1000})}",
                {},
                timeout_seconds,
            )
            models = []
            for item in payload.get("models") or []:
                if not isinstance(item, dict):
                    continue
                actions = item.get("supportedGenerationMethods") or []
                if "generateContent" not in actions:
                    continue
                model_id = item.get("baseModelId") or str(item.get("name", "")).removeprefix("models/")
                if isinstance(model_id, str) and model_id:
                    models.append(model_id)
            return tuple(dict.fromkeys(models)) or available_models(provider_id)

        headers = {"Authorization": f"Bearer {api_key}"}
        if provider_id == "anthropic":
            headers = {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            }
        payload = _get_json(
            f"{base_url.rstrip('/')}/models",
            headers,
            timeout_seconds,
        )
        models = [
            item.get("id")
            for item in payload.get("data") or []
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        ]
        return tuple(dict.fromkeys(models)) or available_models(provider_id)
    except (OSError, ValueError, json.JSONDecodeError):
        return available_models(provider_id)


def _get_json(url: str, headers: dict[str, str], timeout_seconds: float) -> dict:
    request = Request(url, headers=headers, method="GET")
    with urlopen(request, timeout=timeout_seconds) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("model catalog response must be an object")
    return payload


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
