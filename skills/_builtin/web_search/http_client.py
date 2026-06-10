"""HTTP client with per-request random browser fingerprints."""

from __future__ import annotations

import random
import re
import ssl
from dataclasses import dataclass
from typing import Any

import certifi
import httpx

try:
    import tls_client
    from tls_client.exceptions import TLSClientExeption

    _HAS_TLS_CLIENT = True
except ImportError:
    _HAS_TLS_CLIENT = False
    TLSClientExeption = Exception  # type: ignore[misc, assignment]

# TLS / HTTP2 browser profiles (tls_client client_identifier values).
_TLS_PROFILES = [
    "chrome_120",
    "chrome_117",
    "chrome_110",
    "chrome_108",
    "chrome_104",
    "firefox_120",
    "firefox_117",
    "firefox_110",
    "safari_16_0",
    "safari_15_6_1",
    "safari_ios_16_0",
    "safari_ios_15_6",
    "opera_91",
    "opera_90",
]

_ACCEPT_LANGUAGES = [
    "zh-CN,zh;q=0.9,en;q=0.8",
    "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "en-GB,en;q=0.9,zh-CN;q=0.8",
    "zh-TW,zh;q=0.9,en;q=0.8",
]

# HTTP header fingerprints for httpx fallback (no TLS impersonation).
_HTTP_HEADER_PROFILES: list[dict[str, str]] = [
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    },
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
            "Gecko/20100101 Firefox/125.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "none",
    },
    {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
            "(KHTML, like Gecko) Version/17.4 Safari/605.1.15"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    },
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7"
        ),
        "sec-ch-ua": '"Chromium";v="124", "Microsoft Edge";v="124", "Not-A.Brand";v="99"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    },
    {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "sec-ch-ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Linux"',
    },
]


@dataclass
class WebResponse:
    text: str
    content: bytes
    headers: dict[str, str]
    status_code: int

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=httpx.Request("GET", "http://placeholder"),
                response=httpx.Response(self.status_code),
            )


def _random_accept_language() -> str:
    return random.choice(_ACCEPT_LANGUAGES)


def _build_httpx_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    profile = random.choice(_HTTP_HEADER_PROFILES).copy()
    profile["Accept-Language"] = _random_accept_language()
    profile.setdefault("Accept-Encoding", "gzip, deflate, br")
    profile.setdefault("Upgrade-Insecure-Requests", "1")
    if extra:
        profile.update(extra)
    return profile


def _is_ssl_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(
        token in msg
        for token in (
            "ssl",
            "certificate",
            "cert verify",
            "tls",
            "unexpected_eof",
            "eof occurred",
        )
    )


def _looks_like_tls_encoding_corruption(content: bytes) -> bool:
    """Detect tls_client corrupting GBK/GB2312 bodies into UTF-8 replacement bytes."""
    sample = content[:16384]
    if b"\xef\xbf\xbd" not in sample:
        return False
    head = sample.decode("ascii", errors="ignore").lower()
    return bool(re.search(r"charset\s*=\s*gb(?:2312|k|18030)?", head))


def _request_tls_client(
    method: str,
    url: str,
    *,
    timeout: float,
    headers: dict[str, str] | None = None,
    data: Any = None,
) -> WebResponse:
    if not _HAS_TLS_CLIENT:
        raise RuntimeError("tls_client not installed")

    profile = random.choice(_TLS_PROFILES)
    session = tls_client.Session(
        client_identifier=profile,
        random_tls_extension_order=True,
    )
    req_headers = _build_httpx_headers(headers)
    resp = session.execute_request(
        method=method.upper(),
        url=url,
        headers=req_headers,
        data=data,
        timeout_seconds=int(timeout),
        allow_redirects=True,
    )
    raw_headers = getattr(resp, "headers", {}) or {}
    normalized_headers = {
        str(k).lower(): str(v) for k, v in raw_headers.items()
    }
    content = resp.content if isinstance(resp.content, bytes) else resp.content.encode("utf-8")
    return WebResponse(
        text=resp.text,
        content=content,
        headers=normalized_headers,
        status_code=resp.status_code,
    )


def _request_httpx(
    method: str,
    url: str,
    *,
    timeout: float,
    headers: dict[str, str] | None = None,
    data: Any = None,
    verify: bool | str | ssl.SSLContext = True,
) -> WebResponse:
    req_headers = _build_httpx_headers(headers)
    with httpx.Client(timeout=timeout, follow_redirects=True, verify=verify) as client:
        resp = client.request(method.upper(), url, headers=req_headers, data=data)
    return WebResponse(
        text=resp.text,
        content=resp.content,
        headers={k.lower(): v for k, v in resp.headers.items()},
        status_code=resp.status_code,
    )


def web_request(
    method: str,
    url: str,
    *,
    timeout: float = 25.0,
    headers: dict[str, str] | None = None,
    data: Any = None,
) -> WebResponse:
    """Issue an HTTP request with a fresh random browser fingerprint."""
    errors: list[str] = []

    if _HAS_TLS_CLIENT:
        try:
            tls_resp = _request_tls_client(
                method, url, timeout=timeout, headers=headers, data=data
            )
            if not _looks_like_tls_encoding_corruption(tls_resp.content):
                return tls_resp
            errors.append("tls_client: GBK response corrupted, retrying with httpx")
        except TLSClientExeption as exc:
            errors.append(f"tls_client: {exc}")
        except Exception as exc:
            errors.append(f"tls_client: {exc}")

    ca_bundle = certifi.where()
    ssl_ctx = ssl.create_default_context(cafile=ca_bundle)
    for verify in (ssl_ctx, ca_bundle, False):
        try:
            resp = _request_httpx(
                method,
                url,
                timeout=timeout,
                headers=headers,
                data=data,
                verify=verify,
            )
            resp.raise_for_status()
            return resp
        except httpx.HTTPError as exc:
            errors.append(f"httpx(verify={verify!r}): {exc}")
            if not _is_ssl_error(exc):
                raise
        except Exception as exc:
            errors.append(f"httpx(verify={verify!r}): {exc}")
            if not _is_ssl_error(exc):
                raise

    detail = "; ".join(errors[-3:]) if errors else "unknown error"
    raise httpx.ConnectError(f"网络请求失败（已尝试多种指纹与 SSL 策略）— {detail}")
