from __future__ import annotations

import urllib.request
from collections.abc import Callable
from html.parser import HTMLParser

from .browser import BrowserAccessError, validate_public_url
from .registry import ToolDefinition, ToolRegistry

MAX_BODY_BYTES = 512_000
MAX_CONTENT_CHARS = 8_000
FETCH_TIMEOUT_SECONDS = 20.0
_TEXT_CONTENT_PREFIXES = ("text/",)
_TEXT_CONTENT_TYPES = ("application/json", "application/xhtml+xml", "application/xml")
_SKIPPED_ELEMENTS = {"script", "style", "noscript", "template"}

Fetcher = Callable[[str], tuple[int, str, bytes, str]]


class _RedirectValidator(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            validate_public_url(newurl)
        except BrowserAccessError as error:
            raise ValueError(str(error)) from error
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._title_chunks: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in _SKIPPED_ELEMENTS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in _SKIPPED_ELEMENTS and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip_depth:
            return
        if self._in_title:
            self._title_chunks.append(data)
            return
        if data.strip():
            self._chunks.append(data)

    @property
    def title(self) -> str | None:
        title = " ".join(" ".join(self._title_chunks).split())
        return title or None

    @property
    def text(self) -> str:
        return " ".join(" ".join(self._chunks).split())


def _extract_html_text(markup: str) -> tuple[str | None, str]:
    extractor = _TextExtractor()
    extractor.feed(markup)
    return extractor.title, extractor.text


def _http_fetch(url: str) -> tuple[int, str, bytes, str]:
    opener = urllib.request.build_opener(_RedirectValidator())
    request = urllib.request.Request(url, headers={"User-Agent": "AllpathAgent/1.0"})
    with opener.open(request, timeout=FETCH_TIMEOUT_SECONDS) as response:
        body = response.read(MAX_BODY_BYTES + 1)
        content_type = response.headers.get("Content-Type", "")
        return response.status, content_type, body, response.geturl()


def register_web_tools(registry: ToolRegistry, fetch: Fetcher | None = None) -> None:
    fetch_fn = fetch or _http_fetch

    def _web_lookup(arguments: dict) -> dict:
        url = arguments["url"].strip()
        try:
            validate_public_url(url)
        except BrowserAccessError as error:
            raise ValueError(str(error)) from error
        status, content_type, body, final_url = fetch_fn(url)
        media_type = content_type.split(";", 1)[0].strip().lower()
        if not (
            media_type.startswith(_TEXT_CONTENT_PREFIXES)
            or media_type in _TEXT_CONTENT_TYPES
        ):
            raise ValueError(f"web_lookup does not support content type: {media_type or 'unknown'}")
        charset = "utf-8"
        if "charset=" in content_type:
            charset = content_type.split("charset=", 1)[1].split(";", 1)[0].strip() or "utf-8"
        truncated_body = body[:MAX_BODY_BYTES]
        try:
            text = truncated_body.decode(charset, errors="replace")
        except LookupError:
            text = truncated_body.decode("utf-8", errors="replace")
        title: str | None = None
        if media_type in {"text/html", "application/xhtml+xml"}:
            title, text = _extract_html_text(text)
        content_truncated = len(body) > MAX_BODY_BYTES or len(text) > MAX_CONTENT_CHARS
        return {
            "url": final_url,
            "title": title,
            "content": text[:MAX_CONTENT_CHARS],
            "content_truncated": content_truncated,
            "status": status,
        }

    registry.register(
        ToolDefinition(
            name="web_lookup",
            description=(
                "Fetch one public http(s) page and return bounded extracted text. "
                "Public networks only; redirects are re-validated; content is truncated."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "minLength": 8},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
            handler=_web_lookup,
        )
    )
