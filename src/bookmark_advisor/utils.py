from __future__ import annotations

import re
from collections import Counter
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

STOPWORDS = {
    "www",
    "http",
    "https",
    "com",
    "cn",
    "org",
    "net",
    "html",
    "htm",
    "php",
    "asp",
    "aspx",
    "the",
    "and",
    "for",
    "with",
    "from",
    "index",
    "login",
    "home",
    "app",
    "new",
    "tool",
    "tools",
    "page",
    "site",
    "open",
    "api",
}

TRACKING_PREFIXES = ("utm_",)
TRACKING_KEYS = {"spm", "ref", "fbclid", "gclid", "_"}


def normalize_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    if scheme == "http" and netloc.endswith(":80"):
        netloc = netloc[:-3]
    if scheme == "https" and netloc.endswith(":443"):
        netloc = netloc[:-4]
    path = parts.path or "/"
    if path != "/":
        path = path.rstrip("/")
        if not path:
            path = "/"
    query_items = []
    for key, value in parse_qsl(parts.query, keep_blank_values=False):
        lowered = key.lower()
        if lowered in TRACKING_KEYS or any(lowered.startswith(prefix) for prefix in TRACKING_PREFIXES):
            continue
        query_items.append((key, value))
    query = urlencode(sorted(query_items))
    return urlunsplit((scheme, netloc, path, query, ""))


def extract_domain(url: str) -> str:
    parts = urlsplit(url)
    return parts.netloc.lower()


def tokenize(text: str) -> list[str]:
    tokens = []
    for piece in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9]{2,}", text.lower()):
        if piece not in STOPWORDS and not piece.isdigit():
            tokens.append(piece)
    return tokens


def top_tokens(texts: list[str], limit: int = 8) -> list[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for text in texts:
        counter.update(tokenize(text))
    return counter.most_common(limit)


def slugify(value: str) -> str:
    parts = tokenize(value)
    if not parts:
        return "untitled"
    return "-".join(parts[:6])

