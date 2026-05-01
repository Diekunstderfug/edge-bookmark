from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
from collections import Counter
from pathlib import Path
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


def sanitize_for_prompt(text: str) -> str:
    """Strip dangerous characters from text before embedding in AI prompts.

    * Removes null bytes and ASCII control chars (0x00-0x1F) except
      normal space (0x20).
    * Replaces ``\\n``, ``\\r``, ``\\t`` with a single space.
    * Collapses consecutive whitespace into a single space.
    * Strips leading/trailing whitespace.
    * Truncates to 500 characters.
    * Preserves Unicode (CJK, emoji, etc.).
    """
    if not text:
        return ""
    # Remove null bytes and control characters except normal space
    cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
    # Replace \r, \n, \t with space
    cleaned = cleaned.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    # Collapse consecutive whitespace
    cleaned = re.sub(r" {2,}", " ", cleaned)
    cleaned = cleaned.strip()
    return cleaned[:500]


def atomic_write_json(
    path: Path, data: dict[str, object] | list[object], encoding: str = "utf-8"
) -> None:
    """Atomically write JSON data to *path* via temp-file + os.replace().

    * Creates parent directories if needed.
    * Writes a temp file in ``path.parent`` (same filesystem) then replaces
      the destination atomically.
    * Uses ``ensure_ascii=False`` and ``indent=2`` for readable non-ASCII output.
    * Cleans up the temp file on write failure when possible.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(
        dir=str(p.parent), prefix=".atomic_", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, str(p))
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
        raise

