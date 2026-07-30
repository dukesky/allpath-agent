from __future__ import annotations

import atexit
import ipaddress
import re
import shutil
import socket
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit, urlunsplit

from .registry import ToolDefinition, ToolRegistry, ToolRisk

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on optional runtime package
    PlaywrightError = RuntimeError
    sync_playwright = None
    PLAYWRIGHT_AVAILABLE = False


MAX_SNAPSHOT_CHARS = 12_000
MAX_PAGE_TEXT_CHARS = 8_000
MAX_ELEMENTS = 80
MAX_TYPED_CHARS = 10_000
MAX_SCREENSHOT_BYTES = 10 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
_REF = re.compile(r"^e[1-9][0-9]{0,4}$")
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")
_INTERNAL_HOST_SUFFIXES = (".localhost", ".local", ".internal")


class BrowserAccessError(RuntimeError):
    pass


class BrowserBackend(Protocol):
    def navigate(self, url: str) -> dict[str, Any]: ...

    def snapshot(self) -> dict[str, Any]: ...

    def click(self, ref: str) -> dict[str, Any]: ...

    def type_text(self, ref: str, text: str) -> dict[str, Any]: ...

    def screenshot(self, full_page: bool) -> dict[str, Any]: ...

    def download(self, ref: str) -> dict[str, Any]: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class BrowserDiagnostics:
    playwright: bool
    system_chrome: str | None
    bundled_chromium: str | None
    profile_exists: bool

    @property
    def ready(self) -> bool:
        return self.playwright and bool(self.system_chrome or self.bundled_chromium)

    @property
    def next_action(self) -> str:
        if not self.playwright:
            return "Install the full Allpath package dependencies, then restart the Agent."
        if not self.system_chrome and not self.bundled_chromium:
            return "Run /browser install to download isolated Playwright Chromium."
        return "Run /browser test or ask Allpath to inspect a public website."


class BrowserService:
    def __init__(self, backend: BrowserBackend):
        self._backend = backend

    def navigate(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._backend.navigate(arguments["url"])

    def snapshot(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._backend.snapshot()

    def click(self, arguments: dict[str, Any]) -> dict[str, Any]:
        _validate_ref(arguments["ref"])
        return self._backend.click(arguments["ref"])

    def type_text(self, arguments: dict[str, Any]) -> dict[str, Any]:
        _validate_ref(arguments["ref"])
        text = arguments["text"]
        if len(text) > MAX_TYPED_CHARS:
            raise BrowserAccessError("browser text exceeds the 10000 character limit")
        return self._backend.type_text(arguments["ref"], text)

    def screenshot(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._backend.screenshot(bool(arguments.get("full_page", False)))

    def download(self, arguments: dict[str, Any]) -> dict[str, Any]:
        _validate_ref(arguments["ref"])
        return self._backend.download(arguments["ref"])

    def close(self) -> None:
        self._backend.close()


class PlaywrightBrowserBackend:
    def __init__(
        self,
        profile_dir: Path,
        *,
        artifact_dir: Path | None = None,
        download_dir: Path | None = None,
        timeout_ms: int = 30_000,
        resolver: Callable[..., list[tuple[Any, ...]]] = socket.getaddrinfo,
    ):
        if not PLAYWRIGHT_AVAILABLE:
            raise BrowserAccessError("Playwright is not installed")
        self._profile_dir = profile_dir.expanduser().resolve()
        self._artifact_dir = (
            artifact_dir or self._profile_dir.parent / "browser-artifacts"
        ).expanduser().resolve()
        self._download_dir = (
            download_dir or self._profile_dir.parent / "downloads"
        ).expanduser().resolve()
        self._timeout_ms = timeout_ms
        self._resolver = resolver
        self._playwright: Any = None
        self._context: Any = None
        self._page: Any = None
        self._download_authorized = False
        atexit.register(self.close)

    def navigate(self, url: str) -> dict[str, Any]:
        validated = validate_public_url(url, self._resolver)
        page = self._ensure_page()
        try:
            page.goto(validated, wait_until="domcontentloaded", timeout=self._timeout_ms)
        except PlaywrightError as error:
            raise BrowserAccessError(f"browser navigation failed: {str(error)[:240]}") from error
        validate_public_url(page.url, self._resolver)
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        page = self._require_page()
        validate_public_url(page.url, self._resolver)
        try:
            raw = page.evaluate(_SNAPSHOT_SCRIPT, {"maxElements": MAX_ELEMENTS})
        except PlaywrightError as error:
            raise BrowserAccessError(f"browser snapshot failed: {str(error)[:240]}") from error
        result = {
            "url": display_url(page.url),
            "title": str(raw.get("title", ""))[:500],
            "text": str(raw.get("text", ""))[:MAX_PAGE_TEXT_CHARS],
            "elements": list(raw.get("elements", ()))[:MAX_ELEMENTS],
            "truncated": bool(raw.get("truncated")),
        }
        if len(str(result)) > MAX_SNAPSHOT_CHARS:
            result["text"] = result["text"][:2_000]
            result["truncated"] = True
        return result

    def click(self, ref: str) -> dict[str, Any]:
        page = self._require_page()
        locator = self._locator(page, ref)
        try:
            locator.click(timeout=self._timeout_ms)
            if self._context.pages:
                self._page = self._context.pages[-1]
            validate_public_url(self._page.url, self._resolver)
        except PlaywrightError as error:
            raise BrowserAccessError(f"browser click failed: {str(error)[:240]}") from error
        return self.snapshot()

    def type_text(self, ref: str, text: str) -> dict[str, Any]:
        page = self._require_page()
        locator = self._locator(page, ref)
        try:
            locator.fill(text, timeout=self._timeout_ms)
        except PlaywrightError as error:
            raise BrowserAccessError(f"browser typing failed: {str(error)[:240]}") from error
        return {
            "url": display_url(page.url),
            "ref": ref,
            "typed_characters": len(text),
            "text_redacted": True,
        }

    def screenshot(self, full_page: bool) -> dict[str, Any]:
        page = self._require_page()
        validate_public_url(page.url, self._resolver)
        try:
            payload = page.screenshot(full_page=full_page, type="png")
        except PlaywrightError as error:
            raise BrowserAccessError(f"browser screenshot failed: {str(error)[:240]}") from error
        if len(payload) > MAX_SCREENSHOT_BYTES:
            raise BrowserAccessError("browser screenshot exceeds the 10 MB limit")
        self._prepare_private_directory(self._artifact_dir)
        path = self._artifact_dir / f"screenshot-{uuid.uuid4().hex[:12]}.png"
        path.write_bytes(payload)
        path.chmod(0o600)
        return {
            "url": display_url(page.url),
            "path": str(path),
            "bytes": len(payload),
            "full_page": full_page,
        }

    def download(self, ref: str) -> dict[str, Any]:
        page = self._require_page()
        locator = self._locator(page, ref)
        self._download_authorized = True
        try:
            with page.expect_download(timeout=self._timeout_ms) as download_info:
                locator.click(timeout=self._timeout_ms)
            download = download_info.value
            temporary_path = Path(download.path())
            size = temporary_path.stat().st_size
            if size > MAX_DOWNLOAD_BYTES:
                download.cancel()
                raise BrowserAccessError("browser download exceeds the 25 MB limit")
            self._prepare_private_directory(self._download_dir)
            filename = _safe_download_name(download.suggested_filename)
            path = self._download_dir / f"{uuid.uuid4().hex[:8]}-{filename}"
            download.save_as(path)
            path.chmod(0o600)
        except BrowserAccessError:
            raise
        except PlaywrightError as error:
            raise BrowserAccessError(f"browser download failed: {str(error)[:240]}") from error
        finally:
            self._download_authorized = False
        return {
            "url": display_url(download.url),
            "path": str(path),
            "filename": filename,
            "bytes": size,
        }

    def close(self) -> None:
        if self._context is not None:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None
            self._page = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    def _ensure_page(self):
        if self._context is None:
            self._profile_dir.mkdir(parents=True, exist_ok=True)
            self._profile_dir.chmod(0o700)
            self._playwright = sync_playwright().start()
            launch_options = {
                "user_data_dir": str(self._profile_dir),
                "headless": True,
                "accept_downloads": True,
            }
            try:
                self._context = self._playwright.chromium.launch_persistent_context(
                    channel="chrome",
                    **launch_options,
                )
            except PlaywrightError:
                try:
                    self._context = self._playwright.chromium.launch_persistent_context(
                        **launch_options,
                    )
                except PlaywrightError as error:
                    self.close()
                    raise BrowserAccessError(
                        "No supported browser is available. Install Google Chrome or run "
                        "'python -m playwright install chromium'."
                    ) from error
            self._context.set_default_timeout(self._timeout_ms)
            self._context.route("**/*", self._guard_request)
            self._context.on("download", self._reject_unapproved_download)
            self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        return self._page

    def _require_page(self):
        if self._page is None:
            raise BrowserAccessError("no browser session; call browser_navigate first")
        return self._page

    def _locator(self, page: Any, ref: str):
        _validate_ref(ref)
        locator = page.locator(f'[data-allpath-ref="{ref}"]')
        if locator.count() != 1:
            raise BrowserAccessError(
                f"browser ref {ref} is stale or missing; call browser_snapshot again"
            )
        return locator

    def _guard_request(self, route: Any) -> None:
        url = route.request.url
        scheme = urlsplit(url).scheme.lower()
        if scheme in {"about", "blob", "data"}:
            route.continue_()
            return
        try:
            validate_public_url(url, self._resolver)
        except BrowserAccessError:
            route.abort("blockedbyclient")
            return
        route.continue_()

    def _reject_unapproved_download(self, download: Any) -> None:
        if not self._download_authorized:
            download.cancel()

    @staticmethod
    def _prepare_private_directory(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(0o700)


def create_browser_service(profile_dir: Path) -> BrowserService | None:
    if not PLAYWRIGHT_AVAILABLE:
        return None
    return BrowserService(PlaywrightBrowserBackend(profile_dir))


def diagnose_browser(profile_dir: Path) -> BrowserDiagnostics:
    chrome = _system_chrome_path()
    bundled = None
    if PLAYWRIGHT_AVAILABLE:
        playwright = None
        try:
            playwright = sync_playwright().start()
            candidate = Path(playwright.chromium.executable_path).expanduser()
            if candidate.is_file():
                bundled = str(candidate)
        except Exception:
            bundled = None
        finally:
            if playwright is not None:
                try:
                    playwright.stop()
                except Exception:
                    pass
    return BrowserDiagnostics(
        playwright=PLAYWRIGHT_AVAILABLE,
        system_chrome=chrome,
        bundled_chromium=bundled,
        profile_exists=profile_dir.expanduser().exists(),
    )


def reset_browser_profile(profile_dir: Path, service: BrowserService | None = None) -> bool:
    if service is not None:
        service.close()
    path = profile_dir.expanduser()
    if path.is_symlink():
        path.unlink()
        return True
    if not path.exists():
        return False
    if not path.is_dir():
        raise BrowserAccessError("browser profile path is not a directory")
    shutil.rmtree(path)
    return True


def register_browser_tools(registry: ToolRegistry, service: BrowserService) -> None:
    registry.register(
        ToolDefinition(
            name="browser_navigate",
            description=(
                "Open a public HTTP(S) URL in Allpath's isolated browser profile and return a "
                "structured snapshot with stable element refs. Private and local networks are blocked."
            ),
            parameters=_object_schema({"url": {"type": "string", "minLength": 1}}, ("url",)),
            handler=service.navigate,
        )
    )
    registry.register(
        ToolDefinition(
            name="browser_snapshot",
            description="Refresh the current structured browser snapshot and stable element refs.",
            parameters=_object_schema({}, ()),
            handler=service.snapshot,
        )
    )
    registry.register(
        ToolDefinition(
            name="browser_click",
            description=(
                "Click one element ref from the latest browser snapshot. Every click requires "
                "explicit approval in this safety-first MVP."
            ),
            parameters=_object_schema({"ref": {"type": "string", "minLength": 2}}, ("ref",)),
            handler=service.click,
            risk=ToolRisk.SIDE_EFFECT,
        )
    )
    registry.register(
        ToolDefinition(
            name="browser_screenshot",
            description=(
                "Save a PNG screenshot of the current public page in Allpath's private artifact "
                "directory. File creation requires explicit approval."
            ),
            parameters=_object_schema(
                {"full_page": {"type": "boolean"}},
                (),
            ),
            handler=service.screenshot,
            risk=ToolRisk.SIDE_EFFECT,
        )
    )
    registry.register(
        ToolDefinition(
            name="browser_download",
            description=(
                "Click one element ref that starts a download and save at most 25 MB in Allpath's "
                "private download directory. Every download requires explicit approval."
            ),
            parameters=_object_schema({"ref": {"type": "string", "minLength": 2}}, ("ref",)),
            handler=service.download,
            risk=ToolRisk.SIDE_EFFECT,
        )
    )
    registry.register(
        ToolDefinition(
            name="browser_type",
            description=(
                "Replace the text in one editable element ref. Every input requires approval and "
                "the text is redacted from audit records and terminal previews."
            ),
            parameters=_object_schema(
                {
                    "ref": {"type": "string", "minLength": 2},
                    "text": {"type": "string"},
                },
                ("ref", "text"),
            ),
            handler=service.type_text,
            risk=ToolRisk.SIDE_EFFECT,
        )
    )


def validate_public_url(
    url: str,
    resolver: Callable[..., list[tuple[Any, ...]]] = socket.getaddrinfo,
) -> str:
    if len(url) > 2_048:
        raise BrowserAccessError("browser URL exceeds the 2048 character limit")
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise BrowserAccessError("browser URL must use http or https")
    if parsed.username or parsed.password:
        raise BrowserAccessError("browser URL must not contain credentials")
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if not hostname:
        raise BrowserAccessError("browser URL requires a hostname")
    if hostname == "localhost" or hostname.endswith(_INTERNAL_HOST_SUFFIXES):
        raise BrowserAccessError("browser URL points to a local or internal hostname")
    try:
        addresses = [ipaddress.ip_address(hostname)]
    except ValueError:
        try:
            info = resolver(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
        except OSError as error:
            raise BrowserAccessError(f"browser hostname could not be resolved: {hostname}") from error
        addresses = []
        for item in info:
            address = item[4][0]
            try:
                addresses.append(ipaddress.ip_address(address))
            except ValueError:
                continue
    if not addresses or any(not address.is_global for address in addresses):
        raise BrowserAccessError("browser URL resolves to a private or non-public address")
    return url


def display_url(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _validate_ref(ref: str) -> None:
    if not _REF.fullmatch(ref):
        raise BrowserAccessError("browser ref must look like e1 or e24")


def _safe_download_name(suggested_filename: str) -> str:
    name = Path(suggested_filename).name.strip().lstrip(".")
    name = _SAFE_FILENAME.sub("-", name)[:120].strip(".-_")
    return name or "download"


def _system_chrome_path() -> str | None:
    candidates = (
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chrome"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        str(Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate))
    return None


def _object_schema(properties: dict[str, Any], required: tuple[str, ...]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


_SNAPSHOT_SCRIPT = r"""
({maxElements}) => {
  window.__allpathRefCounter = window.__allpathRefCounter || 0;
  const selector = [
    'a[href]', 'button', 'input', 'textarea', 'select', 'summary',
    '[role="button"]', '[role="link"]', '[role="checkbox"]',
    '[role="radio"]', '[role="tab"]', '[contenteditable="true"]'
  ].join(',');
  const visible = (element) => {
    const style = window.getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
  };
  const roleFor = (element) => {
    if (element.getAttribute('role')) return element.getAttribute('role');
    const tag = element.tagName.toLowerCase();
    if (tag === 'a') return 'link';
    if (tag === 'button') return 'button';
    if (tag === 'textarea') return 'textbox';
    if (tag === 'select') return 'combobox';
    if (tag === 'input') return element.type || 'textbox';
    return tag;
  };
  const safeHref = (element) => {
    if (!element.href) return null;
    try {
      const url = new URL(element.href, document.baseURI);
      return `${url.origin}${url.pathname}`;
    } catch (_) { return null; }
  };
  const candidates = Array.from(document.querySelectorAll(selector)).filter(visible);
  const elements = candidates.slice(0, maxElements).map((element) => {
    if (!element.dataset.allpathRef) {
      window.__allpathRefCounter += 1;
      element.dataset.allpathRef = `e${window.__allpathRefCounter}`;
    }
    const name = element.getAttribute('aria-label') || element.innerText ||
      element.getAttribute('placeholder') || element.getAttribute('title') || '';
    return {
      ref: element.dataset.allpathRef,
      role: roleFor(element),
      name: String(name).replace(/\s+/g, ' ').trim().slice(0, 240),
      href: safeHref(element),
      disabled: Boolean(element.disabled || element.getAttribute('aria-disabled') === 'true')
    };
  });
  return {
    title: document.title || '',
    text: String(document.body?.innerText || '').slice(0, 8000),
    elements,
    truncated: candidates.length > maxElements || String(document.body?.innerText || '').length > 8000
  };
}
"""
