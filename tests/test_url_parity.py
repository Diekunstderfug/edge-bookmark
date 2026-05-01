"""Parity tests for URL normalization: Python vs JS.

Strategy
========
Python ``normalize_url()`` is the source of truth.  Each fixture is an
``(input_url, expected_output)`` pair verified against the live Python
function.  When Node.js is available on ``PATH``, the same fixtures are
also validated against the JS ``normalizeUrl()`` extracted from
``extension/service_worker.js``; the test is skipped otherwise.

CJK path handling is the primary cross-language risk: Python's
``urlunsplit`` preserves raw Unicode path segments, while the JS
``URL`` constructor percent-encodes them.  The JS function works around
this by calling ``decodeURIComponent(parsed.pathname)`` and assembling
the result string manually instead of using ``parsed.toString()``.

Known parity limits
===================
- Python ``urlencode`` uses ``quote_plus`` (space → ``+``), while JS
  ``encodeURIComponent`` uses ``%20``.  Only affects URLs whose query
  values contain literal spaces.  No current fixture triggers this.
- Already-percent-encoded CJK paths (e.g. ``/path/%E6%97%A5``) are
  preserved as-is by Python but decoded by JS ``new URL()``.  This
  divergence is inherent to using ``new URL()`` and only affects inputs
  that are already percent-encoded; raw CJK input (the common case) is
  handled correctly by both sides.
"""

import os
import re
import shutil
import subprocess
import unittest

from bookmark_advisor.utils import normalize_url

# fmt: off
FIXTURES: list[tuple[str, str]] = [
    # 1. Case normalization — scheme and netloc lowercased
    (
        "https://Example.COM/Path/",
        "https://example.com/Path",
    ),
    # 2. Default port removal: http :80
    (
        "http://example.com:80/path",
        "http://example.com/path",
    ),
    # 3. Default port removal: https :443
    (
        "https://example.com:443/path",
        "https://example.com/path",
    ),
    # 4. utm_* prefix stripping (multiple utm_ params removed, non-utm kept)
    (
        "https://example.com/path?utm_source=ga&utm_medium=email&id=123",
        "https://example.com/path?id=123",
    ),
    # 5. All tracking keys stripped: spm, ref, fbclid, gclid, _
    (
        "https://example.com/?spm=123&ref=search&fbclid=abc&gclid=def&_=123&q=test",
        "https://example.com/?q=test",
    ),
    # 6. Query param sorting (z, a, m → a, m, z)
    (
        "https://example.com/path?z=3&a=1&m=2",
        "https://example.com/path?a=1&m=2&z=3",
    ),
    # 7. Fragment dropped
    (
        "https://example.com/path#section",
        "https://example.com/path",
    ),
    # 8. Root path preserved
    (
        "https://example.com/",
        "https://example.com/",
    ),
    # 9. Bare domain gets trailing slash
    (
        "https://example.com",
        "https://example.com/",
    ),
    # 10. Empty string
    (
        "",
        "",
    ),
    # 11. CJK path segments — raw Unicode preserved
    (
        "https://example.com/日语/路径",
        "https://example.com/日语/路径",
    ),
    # 12. CJK query value (percent-encoded by Python)
    (
        "https://example.com/日语/路径?q=搜索",
        "https://example.com/日语/路径?q=%E6%90%9C%E7%B4%A2",
    ),
    # 13. Duplicate && in query (empty pair between) — empty pairs dropped
    (
        "https://example.com/?a=1&&b=2",
        "https://example.com/?a=1&b=2",
    ),
    # 14. Case-sensitive key sort (A before a)
    (
        "https://example.com/?A=2&a=1",
        "https://example.com/?A=2&a=1",
    ),
    # 15. UTM_SOURCE (uppercase utm_ prefix) stripped case-insensitively
    (
        "https://example.com/?UTM_SOURCE=ga",
        "https://example.com/",
    ),
    # 16. Multiple utm_ params removed, non-utm kept and sorted
    (
        "https://example.com/?utm_campaign=spring&utm_source=twitter&keep=yes",
        "https://example.com/?keep=yes",
    ),
    # 17. Non-default port preserved
    (
        "http://example.com:8080/path",
        "http://example.com:8080/path",
    ),
    # 18. Trailing slash stripped from non-root path
    (
        "https://example.com/path/",
        "https://example.com/path",
    ),
    # 19. Multiple trailing slashes stripped, root path stays
    (
        "https://example.com///",
        "https://example.com/",
    ),
    # 20. _ is a tracking key; __ (double underscore) is NOT
    (
        "https://example.com/?_=1&__=2",
        "https://example.com/?__=2",
    ),
    # 21. Case-sensitive keys sorted (Foo before foo)
    (
        "https://example.com/?foo=bar&Foo=baz",
        "https://example.com/?Foo=baz&foo=bar",
    ),
    # 22. Empty-value params dropped (keep_blank_values=False)
    (
        "https://example.com/?a=&b=2",
        "https://example.com/?b=2",
    ),
    # 23. Three params sorted alphabetically
    (
        "https://example.com/?b=2&a=1&c=3",
        "https://example.com/?a=1&b=2&c=3",
    ),
    # 24. Default port + utm_ prefix both cleaned
    (
        "https://example.com:443/?utm_test=1",
        "https://example.com/",
    ),
    # 25. Real-world GitHub URL with utm_source notification param
    (
        "https://github.com/user/repo/issues/1?utm_source=notification",
        "https://github.com/user/repo/issues/1",
    ),
    # 26. CJK path + tracking param + sorting
    (
        "https://example.com/编程/Python?utm_source=weixin&lang=zh&page=1",
        "https://example.com/编程/Python?lang=zh&page=1",
    ),
]
# fmt: on

_JS_SRC_PATH = os.path.join(
    os.path.dirname(__file__), "..", "extension", "service_worker.js"
)


def _has_node() -> bool:
    return shutil.which("node") is not None


def _extract_js_normalize_url() -> str:
    with open(_JS_SRC_PATH, encoding="utf-8") as fh:
        src = fh.read()
    m = re.search(r"function normalizeUrl\(url\) \{[\s\S]*?\n\}", src)
    if not m:
        raise RuntimeError("could not extract normalizeUrl from service_worker.js")
    return m.group(0)


def _run_js_fixtures(js_fn_body: str, fixtures: list[tuple[str, str]]) -> str:
    lines = [js_fn_body, "const fixtures = ["]
    for raw, expected in fixtures:
        lines.append(f"  {raw!r}, {expected!r},")
    lines.append("];")
    lines.append(
        "let bad = [];"
        "for (let i = 0; i < fixtures.length; i += 2) {"
        "  const got = normalizeUrl(fixtures[i]);"
        "  if (got !== fixtures[i+1]) bad.push({i: i/2, input: fixtures[i],"
        "    expected: fixtures[i+1], got});"
        "}"
        "if (bad.length) {"
        "  for (const f of bad) console.log(JSON.stringify(f));"
        "  process.exit(1);"
        "}"
        "console.log('ALL PASS');"
    )
    proc = subprocess.run(
        ["node", "-e", "\n".join(lines)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return proc.stdout.strip() + proc.stderr.strip()


class TestNormalizeUrlParity(unittest.TestCase):
    """Verify Python normalize_url() output for each fixture."""

    def test_fixture_count(self):
        self.assertGreaterEqual(len(FIXTURES), 20)

    def test_fixtures(self):
        for raw, expected in FIXTURES:
            with self.subTest(raw=raw):
                result = normalize_url(raw)
                self.assertEqual(
                    result,
                    expected,
                    f"normalize_url({raw!r}) = {result!r}, expected {expected!r}",
                )

    def test_cjk_path_not_percent_encoded_in_python_output(self):
        cjk_url = "https://example.com/日语/路径"
        result = normalize_url(cjk_url)
        self.assertIn("日语", result)
        self.assertNotIn("%E6%97%A5%E8%AF%AD", result)

    def test_js_source_does_not_use_toString_for_return(self):
        with open(_JS_SRC_PATH, encoding="utf-8") as fh:
            src = fh.read()
        m = re.search(
            r"function normalizeUrl\(url\) \{[\s\S]*?\n\}", src
        )
        if m is None:
            self.fail("normalizeUrl function not found in service_worker.js")
        body = m.group(0)
        self.assertNotIn(
            "parsed.toString()",
            body,
            "normalizeUrl must not use parsed.toString() — it encodes CJK paths",
        )
        self.assertIn(
            "decodeURIComponent",
            body,
            "normalizeUrl must decode parsed.pathname to preserve raw CJK",
        )

    @unittest.skipUnless(_has_node(), "Node.js not available on PATH")
    def test_js_parity_with_node(self):
        js_fn = _extract_js_normalize_url()
        output = _run_js_fixtures(js_fn, FIXTURES)
        self.assertEqual(
            output,
            "ALL PASS",
            f"JS normalizeUrl fixture failures:\n{output}",
        )


if __name__ == "__main__":
    unittest.main()
