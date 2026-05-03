from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

from app.core.config import get_settings

try:
    from urllib.request import Request, urlopen
    from urllib.error import URLError
except ImportError:
    pass


BLOCKED_NETWORKS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]


@dataclass
class WebPage:
    url: str
    title: str
    text: str
    snippet: str
    status_code: int
    content_length: int


def _is_private_host(hostname: str) -> bool:
    try:
        addr = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
        for family, _, _, _, sockaddr in addr:
            ip = ipaddress.ip_address(sockaddr[0])
            for network in BLOCKED_NETWORKS:
                if ip in network:
                    return True
    except (socket.gaierror, ValueError):
        return True
    return False


def _extract_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _html_to_text(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = re.sub(r"&[a-z]+;", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_page(url: str, *, timeout: float = 10.0, max_bytes: int = 500_000) -> WebPage:
    settings = get_settings()
    parsed = urlparse(url)

    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported scheme: {parsed.scheme}")

    if not parsed.hostname:
        raise ValueError("URL has no hostname")

    if _is_private_host(parsed.hostname):
        raise ValueError(f"Blocked private/internal host: {parsed.hostname}")

    req = Request(url, method="GET")
    req.add_header("User-Agent", "SmartCloud-X-Research/1.0")
    req.add_header("Accept", "text/html,text/plain,*/*")

    response = urlopen(req, timeout=timeout)
    status_code = response.getcode()

    content = b""
    total = 0
    for chunk in response:
        content += chunk
        total += len(chunk)
        if total >= max_bytes:
            break

    html = content.decode("utf-8", errors="replace")
    title = _extract_title(html)
    text = _html_to_text(html)
    snippet = text[:300] if text else ""

    return WebPage(
        url=url,
        title=title or url,
        text=text,
        snippet=snippet,
        status_code=status_code,
        content_length=len(content),
    )
