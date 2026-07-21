"""Independent tests for the extension fast-rules loader."""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import Any, cast


ROOT = Path(__file__).resolve().parents[1]
FAST_RULES = ROOT / "extension" / "ai" / "fast_rules.js"

EXPECTED_FALLBACK = {
    "defaults": {
        "protect_root_loose_bookmarks": True,
        "allow_new_folders_in_advise": True,
    },
    "protected_paths": ["/收藏夹栏", "/其他收藏夹", "/移动收藏夹", "/工作区"],
    "category_hints": {},
    "folder_relocations": [],
    "bookmark_relocations": [],
}


@unittest.skipUnless(shutil.which("node"), "node is required for extension JS tests")
class ExtensionFastRulesTest(unittest.TestCase):
    def _node_eval(self, body: str) -> Any:
        script = f"""
          const fastRulesPath = {json.dumps(str(FAST_RULES))};
          require(fastRulesPath);
          {body}
        """
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        output = completed.stdout.strip().splitlines()
        self.assertTrue(output, completed.stderr)
        return json.loads(output[-1])

    def test_success_loads_packaged_json_and_caches_first_result(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                r"""
                const calls = [];
                let fetchCount = 0;
                const expected = {
                  defaults: { protect_root_loose_bookmarks: false, allow_new_folders_in_advise: false },
                  protected_paths: ['/Custom'],
                  category_hints: { AI: ['llm'] },
                  folder_relocations: [{ from: '/A', to: '/B' }],
                  bookmark_relocations: [{ domain: 'example.com', to: '/B' }],
                };
                const instance = globalThis.BookmarkAdvisor.AI.FastRules.create({
                  chrome: {
                    runtime: {
                      getURL: (path) => {
                        calls.push(path);
                        return `chrome-extension://test/${path}`;
                      },
                    },
                  },
                  fetch: async (url) => {
                    fetchCount += 1;
                    calls.push(url);
                    return { ok: true, status: 200, json: async () => expected };
                  },
                  log: (message, level) => { calls.push([level, message]); },
                });

                (async () => {
                  const before = instance.get();
                  const first = await instance.load();
                  const second = await instance.load();
                  console.log(JSON.stringify({
                    before,
                    first,
                    sameObject: first === second,
                    fetchCount,
                    source: instance.getSource(),
                    diagnostic: instance.getDiagnostic(),
                    calls,
                  }));
                })();
                """
            ),
        )
        self.assertEqual(result["before"], EXPECTED_FALLBACK)
        self.assertEqual(
            result["first"],
            {
                "defaults": {
                    "protect_root_loose_bookmarks": False,
                    "allow_new_folders_in_advise": False,
                },
                "protected_paths": ["/Custom"],
                "category_hints": {"AI": ["llm"]},
                "folder_relocations": [{"from": "/A", "to": "/B"}],
                "bookmark_relocations": [{"domain": "example.com", "to": "/B"}],
            },
        )
        self.assertEqual(result["sameObject"], True)
        self.assertEqual(result["fetchCount"], 1)
        self.assertEqual(result["source"], "extension-fast-rules-json")
        self.assertEqual(result["diagnostic"], "")
        self.assertEqual(result["calls"][:2], ["fast_rules.json", "chrome-extension://test/fast_rules.json"])

    def test_http_failure_uses_fallback_and_is_cached(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                r"""
                const logs = [];
                let fetchCount = 0;
                const instance = globalThis.BookmarkAdvisor.AI.FastRules.create({
                  chrome: { runtime: { getURL: () => 'chrome-extension://test/fast_rules.json' } },
                  fetch: async () => {
                    fetchCount += 1;
                    return { ok: false, status: 503 };
                  },
                  log: (message, level) => { logs.push({ message, level }); },
                });

                (async () => {
                  const first = await instance.load();
                  const second = await instance.load();
                  console.log(JSON.stringify({
                    first,
                    sameObject: first === second,
                    fetchCount,
                    source: instance.getSource(),
                    diagnostic: instance.getDiagnostic(),
                    logs,
                  }));
                })();
                """
            ),
        )
        diagnostic = "fast_rules.json load failed: HTTP 503. Using built-in fallback rules."
        self.assertEqual(result["first"], EXPECTED_FALLBACK)
        self.assertEqual(result["sameObject"], True)
        self.assertEqual(result["fetchCount"], 1)
        self.assertEqual(result["source"], "extension-embedded-fast-rules-fallback")
        self.assertEqual(result["diagnostic"], diagnostic)
        self.assertEqual(result["logs"], [{"message": diagnostic, "level": "warn"}])

    def test_fetch_exception_uses_exception_message_in_diagnostic(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                r"""
                const logs = [];
                const instance = globalThis.BookmarkAdvisor.AI.FastRules.create({
                  chrome: { runtime: { getURL: () => 'chrome-extension://test/fast_rules.json' } },
                  fetch: async () => { throw new Error('network down'); },
                  log: (message, level) => { logs.push([level, message]); },
                });

                instance.load().then((rules) => {
                  console.log(JSON.stringify({
                    rules,
                    source: instance.getSource(),
                    diagnostic: instance.getDiagnostic(),
                    logs,
                  }));
                });
                """
            ),
        )
        diagnostic = "fast_rules.json load failed: network down. Using built-in fallback rules."
        self.assertEqual(result["rules"], EXPECTED_FALLBACK)
        self.assertEqual(result["source"], "extension-embedded-fast-rules-fallback")
        self.assertEqual(result["diagnostic"], diagnostic)
        self.assertEqual(result["logs"], [["warn", diagnostic]])

    def test_missing_chrome_runtime_falls_back_without_fetching(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                r"""
                let fetchCount = 0;
                const instance = globalThis.BookmarkAdvisor.AI.FastRules.create({
                  fetch: async () => { fetchCount += 1; return { ok: true, json: async () => ({}) }; },
                  log: () => {},
                });

                instance.load().then((rules) => {
                  console.log(JSON.stringify({
                    rules,
                    fetchCount,
                    source: instance.getSource(),
                    diagnostic: instance.getDiagnostic(),
                  }));
                });
                """
            ),
        )
        self.assertEqual(result["rules"], EXPECTED_FALLBACK)
        self.assertEqual(result["fetchCount"], 0)
        self.assertEqual(result["source"], "extension-embedded-fast-rules-fallback")
        self.assertEqual(
            result["diagnostic"],
            "fast_rules.json load failed: chrome.runtime.getURL unavailable. "
            "Using built-in fallback rules.",
        )

    def test_use_fallback_sets_state_and_prevents_later_fetch(self) -> None:
        result = cast(
            dict[str, object],
            self._node_eval(
                r"""
                let fetchCount = 0;
                const logs = [];
                const instance = globalThis.BookmarkAdvisor.AI.FastRules.create({
                  chrome: { runtime: { getURL: () => 'chrome-extension://test/fast_rules.json' } },
                  fetch: async () => {
                    fetchCount += 1;
                    return { ok: true, json: async () => ({ protected_paths: ['/Fetched'] }) };
                  },
                  log: (message, level) => { logs.push([level, message]); },
                });
                const fallback = instance.useFallback('manual fallback');

                instance.load().then((loaded) => {
                  console.log(JSON.stringify({
                    fallback,
                    sameObject: fallback === loaded && loaded === instance.get(),
                    fetchCount,
                    source: instance.getSource(),
                    diagnostic: instance.getDiagnostic(),
                    logs,
                  }));
                });
                """
            ),
        )
        diagnostic = "fast_rules.json load failed: manual fallback. Using built-in fallback rules."
        self.assertEqual(result["fallback"], EXPECTED_FALLBACK)
        self.assertEqual(result["sameObject"], True)
        self.assertEqual(result["fetchCount"], 0)
        self.assertEqual(result["source"], "extension-embedded-fast-rules-fallback")
        self.assertEqual(result["diagnostic"], diagnostic)
        self.assertEqual(result["logs"], [["warn", diagnostic]])


if __name__ == "__main__":
    unittest.main()
