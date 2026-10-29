"""Small HTTPS JSON client. Public market-data only."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

USER_AGENT = "cross-venue-arb/0.1 (observe-only research)"
MAX_BYTES = 8_000_000

T = TypeVar("T")


class HttpStatusError(Exception):
    def __init__(self, url: str, status: int, detail: str) -> None:
        self.url = url
        self.status = status
        self.detail = detail
        super().__init__(f"HTTP {status} {detail}")


class _SameHostHttpsRedirect(HTTPRedirectHandler):
    """Follow HTTPS redirects on the same host. Block off-host hops."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        original = urlparse(req.full_url)
        target = urlparse(newurl)
        if target.scheme != "https" or not target.hostname or target.hostname != original.hostname:
            raise HttpStatusError(req.full_url, code, "redirect blocked")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def join_url(base: str, path: str, query: dict[str, str] | None = None) -> str:
    if not base.startswith("https://"):
        raise HttpStatusError(base, 0, "base URL must be https")
    url = base.rstrip("/") + "/" + path.lstrip("/")
    if query:
        url = url + "?" + urlencode(query)
    return url


def request_json(
    method: str,
    url: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> Any:
    if not url.startswith("https://"):
        raise HttpStatusError(url, 0, "only https URLs are allowed")
    data = None
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method.upper())
    opener = build_opener(_SameHostHttpsRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:
            body = response.read(MAX_BYTES + 1)
            status = getattr(response, "status", 200)
    except HTTPError as exc:
        raw = exc.read(2000)
        raise HttpStatusError(url, exc.code, _snippet(raw)) from None
    except URLError as exc:
        raise HttpStatusError(url, 0, str(exc.reason)) from None
    except TimeoutError as exc:
        raise HttpStatusError(url, 0, f"timeout: {exc}") from None
    if len(body) > MAX_BYTES:
        raise HttpStatusError(url, status, "response exceeded size cap")
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HttpStatusError(url, status, f"invalid JSON ({exc})") from None


def map_parallel(fn: Callable[[T], Any], items: list[T], max_workers: int = 4) -> list[Any]:
    if not items:
        return []
    workers = max(1, min(max_workers, len(items)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, items))


def _snippet(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace").strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        message = payload.get("msg") or payload.get("message")
        if isinstance(message, str) and message.strip():
            text = message.strip()
    text = " ".join(text.split())
    if len(text) > 240:
        return text[:240] + "..."
    return text or "empty body"
