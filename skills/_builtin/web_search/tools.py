"""Web search skill tools."""

from __future__ import annotations

import importlib.util
import ipaddress
import json
import re
import socket
import sys
import time
import xml.etree.ElementTree as ET
from html import unescape
from pathlib import Path
from urllib.parse import quote_plus, urlparse


def _load_sibling_module(name: str):
    path = Path(__file__).with_name(f"{name}.py")
    mod_name = f"web_search_{name}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if not spec or not spec.loader:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


http_client = _load_sibling_module("http_client")
page_parser = _load_sibling_module("page_parser")

TOOLS = [
    {
        "name": "web_search",
        "description": "搜索互联网获取最新信息，返回标题、摘要和链接。",
        "parameters": {
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "max_results": {
                    "type": "integer",
                    "description": "最大结果数，默认 5，最大 10",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "fetch_web_page",
        "description": (
            "抓取指定 URL 并解析内容，用于在 web_search 获得链接后深入阅读。"
            "支持 HTML、JSON API、XML/RSS、PDF、DOCX、XLSX、EPUB、YAML、CSV、Markdown 等，"
            "返回标题和正文摘要。"
        ),
        "parameters": {
            "properties": {
                "url": {"type": "string", "description": "要抓取的网页 URL（须为 http/https）"},
                "max_chars": {
                    "type": "integer",
                    "description": "返回正文最大字符数，默认 8000，最大 20000",
                },
            },
            "required": ["url"],
        },
    },
]

_MAX_RESPONSE_BYTES = 2 * 1024 * 1024

# Leading dates (e.g. "2026年6月10日 …") cause Bing to overweight the year token.
_DATE_PREFIX_RE = re.compile(
    r"^(\d{4}年\d{1,2}月\d{1,2}日|\d{4}-\d{1,2}-\d{1,2}|\d{4}/\d{1,2}/\d{1,2})\s+"
)
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _normalize_search_query(query: str) -> str:
    """Move a leading date after the subject terms for better Bing relevance."""
    match = _DATE_PREFIX_RE.match(query)
    if not match:
        return query
    date_part = match.group(1)
    rest = query[match.end() :].strip()
    if not rest:
        return query
    return f"{rest} {date_part}"


def _build_bing_search_url(query: str) -> str:
    encoded = quote_plus(query)
    if _CJK_RE.search(query):
        return (
            f"https://cn.bing.com/search?q={encoded}"
            "&setlang=zh-Hans&cc=CN&ensearch=0"
        )
    return f"https://www.bing.com/search?q={encoded}"


def _build_baidu_search_url(query: str) -> str:
    return f"https://www.baidu.com/s?wd={quote_plus(query)}&rn=10"


def _bing_safe_query(query: str) -> str:
    """Strip quotes/operators that make Bing match unrelated tokens (e.g. \"6\")."""
    q = query.replace('"', " ").replace("'", " ")
    q = re.sub(r"\s+", " ", q).strip()
    return _normalize_search_query(q)


def _simplify_search_query(query: str) -> str:
    q = re.sub(r"site:\S+", "", query)
    q = q.replace('"', " ").replace("'", " ")
    q = _DATE_PREFIX_RE.sub("", q)
    return re.sub(r"\s+", " ", q).strip()


def _extract_search_terms(query: str) -> list[str]:
    q = re.sub(r"site:\S+", "", query)
    q = q.replace('"', "").replace("'", "")
    terms: list[str] = []
    terms.extend(re.findall(r"[\u4e00-\u9fff]{2,}", q))
    terms.extend(re.findall(r"\d{4,}", q))
    terms.extend(re.findall(r"[a-zA-Z]{3,}", q))
    seen: set[str] = set()
    unique: list[str] = []
    for term in sorted(terms, key=len, reverse=True):
        key = term.lower()
        if key not in seen:
            seen.add(key)
            unique.append(key)
    return unique


def _results_look_relevant(query: str, results: list[dict[str, str]]) -> bool:
    terms = _extract_search_terms(query)
    if not terms:
        return bool(results)
    if not results:
        return False
    primary = terms[:6]
    matched = 0
    for item in results[:5]:
        text = f"{item['title']} {item['snippet']}".lower()
        if any(term in text for term in primary):
            matched += 1
    threshold = max(1, min(3, len(results[:5]) // 2))
    return matched >= threshold


def _fetch_search_results(
    engine: str,
    search_query: str,
    max_results: int,
) -> tuple[list[dict[str, str]], str]:
    if engine == "baidu":
        search_url = _build_baidu_search_url(search_query)
        parse = _parse_baidu_html
    else:
        search_url = _build_bing_search_url(search_query)
        parse = _parse_bing_html

    last_error = ""
    for attempt in range(2):
        try:
            resp = http_client.web_request("GET", search_url, timeout=20.0)
            resp.raise_for_status()
        except Exception as e:
            last_error = str(e)
            if attempt < 1:
                time.sleep(1.0 * (attempt + 1))
                continue
            return [], last_error

        results = parse(resp.text, max_results)
        if results:
            return results, ""
        if engine == "bing" and "b_algo" in resp.text and attempt < 1:
            time.sleep(1.0 * (attempt + 1))
            continue
        break
    return [], last_error


def web_search(query: str, max_results: int = 5) -> str:
    original_query = query.strip()
    if not original_query:
        return "错误：搜索关键词不能为空"
    max_results = max(1, min(int(max_results), 10))
    last_error = ""
    results: list[dict[str, str]] = []

    attempts: list[tuple[str, str]] = []
    if _CJK_RE.search(original_query):
        attempts.append(("baidu", original_query))
        attempts.append(("bing", _bing_safe_query(original_query)))
        simplified = _simplify_search_query(original_query)
        if simplified and simplified != original_query:
            attempts.append(("baidu", simplified))
            attempts.append(("bing", _bing_safe_query(simplified)))
    else:
        attempts.append(("bing", original_query))

    seen_queries: set[tuple[str, str]] = set()
    for engine, search_query in attempts:
        if not search_query:
            continue
        key = (engine, search_query)
        if key in seen_queries:
            continue
        seen_queries.add(key)

        batch, err = _fetch_search_results(engine, search_query, max_results)
        if err:
            last_error = err
        if not batch:
            continue
        if engine == "baidu":
            results = batch
            break
        if _results_look_relevant(original_query, batch):
            results = batch
            break
        if not results:
            results = batch

    if not results:
        if last_error:
            return f"错误：网络搜索请求失败 — {last_error}"
        return (
            f"未找到与「{original_query}」相关的搜索结果。"
            "（可能遭遇搜索引擎限流，请稍后重试或换用更短的中文关键词。）"
        )

    lines = [f"搜索「{original_query}」共 {len(results)} 条结果：\n"]
    for i, item in enumerate(results, 1):
        lines.append(f"{i}. {item['title']}")
        if item["snippet"]:
            lines.append(f"   {item['snippet']}")
        lines.append(f"   {item['url']}\n")
    return "\n".join(lines)


def fetch_web_page(url: str, max_chars: int = 8000) -> str:
    url = url.strip()
    err = _validate_url(url)
    if err:
        return err
    max_chars = max(500, min(int(max_chars), 20_000))

    try:
        resp = http_client.web_request("GET", url, timeout=25.0)
        resp.raise_for_status()
    except Exception as e:
        return f"错误：网页请求失败 — {e}"

    if len(resp.content) > _MAX_RESPONSE_BYTES:
        return f"错误：页面过大（>{_MAX_RESPONSE_BYTES // 1024 // 1024}MB），已拒绝处理"

    content_type = resp.headers.get("content-type", "")
    try:
        title, body, fmt = page_parser.parse_response(
            resp.content,
            content_type,
            url=url,
        )
    except json.JSONDecodeError as e:
        return f"错误：JSON 解析失败 — {e}"
    except ET.ParseError as e:
        return f"错误：XML 解析失败 — {e}"
    except Exception as e:
        return f"错误：内容解析失败 — {e}"

    if not body:
        return f"未能从响应提取正文。\nURL: {url}\n类型: {fmt or 'unknown'}\n标题: {title or '(无)'}"

    if body.startswith("错误："):
        return body

    if len(body) > max_chars:
        body = body[:max_chars] + f"\n\n…（正文已截断，共约 {len(body)} 字符）"

    lines = [f"URL: {url}"]
    if fmt:
        lines.append(f"类型: {fmt}")
    if title:
        lines.append(f"标题: {title}")
    lines.append("")
    lines.append(body)
    return "\n".join(lines)


def _validate_url(url: str) -> str | None:
    if not url:
        return "错误：URL 不能为空"
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "错误：仅支持 http/https 协议"
    host = parsed.hostname
    if not host:
        return "错误：无效的 URL"
    if host == "localhost" or host.endswith(".local"):
        return "错误：不允许访问本地地址"
    try:
        for _, _, _, _, sockaddr in socket.getaddrinfo(host, None):
            ip = ipaddress.ip_address(sockaddr[0])
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                return "错误：不允许访问内网地址"
    except socket.gaierror:
        return f"错误：无法解析域名 — {host}"
    return None


def _clean_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text).strip()


def _parse_bing_html(html: str, limit: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for block in re.split(r'<li class="b_algo"', html, flags=re.IGNORECASE)[1:]:
        title_match = re.search(
            r'<h2[^>]*>\s*<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            block,
            re.DOTALL | re.IGNORECASE,
        )
        if not title_match:
            continue
        url = unescape(title_match.group(1))
        title = _clean_html(title_match.group(2))
        snippet_match = re.search(
            r'<div class="b_caption"[^>]*>.*?<p[^>]*>(.*?)</p>',
            block,
            re.DOTALL | re.IGNORECASE,
        )
        snippet = _clean_html(snippet_match.group(1)) if snippet_match else ""
        if url.startswith("//"):
            url = "https:" + url
        results.append({"title": title, "snippet": snippet, "url": url})
        if len(results) >= limit:
            break
    return results


def _parse_baidu_html(html: str, limit: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    for block in re.split(
        r'<div[^>]*class="[^"]*\bc-container\b[^"]*"[^>]*>',
        html,
        flags=re.IGNORECASE,
    )[1:]:
        title_match = re.search(
            r'<h3[^>]*class="[^"]*\bt\b[^"]*"[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            block,
            re.DOTALL | re.IGNORECASE,
        )
        if not title_match:
            title_match = re.search(
                r'<a[^>]*class="[^"]*c-title[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
                block,
                re.DOTALL | re.IGNORECASE,
            )
        if not title_match:
            continue
        url = unescape(title_match.group(1))
        title = _clean_html(title_match.group(2))
        if not title or not url:
            continue
        snippet_match = re.search(
            r'<div[^>]*class="[^"]*c-abstract[^"]*"[^>]*>(.*?)</div>',
            block,
            re.DOTALL | re.IGNORECASE,
        )
        if not snippet_match:
            snippet_match = re.search(
                r'<span[^>]*class="[^"]*content-right[^"]*"[^>]*>(.*?)</span>',
                block,
                re.DOTALL | re.IGNORECASE,
            )
        snippet = _clean_html(snippet_match.group(1)) if snippet_match else ""
        results.append({"title": title, "snippet": snippet, "url": url})
        if len(results) >= limit:
            break
    return results
