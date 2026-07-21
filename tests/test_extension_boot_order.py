"""Load-order contracts for the extension's three runtime entrypoints."""

from __future__ import annotations

import json
import re
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"


class _ScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.sources: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "script":
            return
        source = dict(attrs).get("src")
        if source:
            self.sources.append(source)


def _html_scripts(filename: str) -> list[str]:
    parser = _ScriptParser()
    parser.feed((EXTENSION / filename).read_text(encoding="utf-8"))
    return parser.sources


def _service_worker_imports() -> list[str]:
    source = (EXTENSION / "service_worker.js").read_text(encoding="utf-8")
    match = re.search(r"importScripts\((.*?)\);", source, re.DOTALL)
    if not match:
        raise AssertionError("service_worker.js must declare importScripts(...)")
    return re.findall(r'["\']([^"\']+)["\']', match.group(1))


class ExtensionBootOrderTest(unittest.TestCase):
    foundation = [
        "shared/message_protocol.js",
        "shared/plan_schema.js",
        "shared/ai_endpoint.js",
        "shared/path_utils.js",
        "shared/storage.js",
        "action_constants.js",
        "storage_helpers.js",
    ]
    ai_modules = [
        "ai/fast_rules.js",
        "ai/snapshot_model.js",
        "ai/batching.js",
        "ai/prompt_codec.js",
        "ai/response_codec.js",
        "ai/provider_client.js",
        "ai/plan_compiler.js",
    ]

    def test_entrypoint_script_orders_are_dependency_first(self) -> None:
        self.assertEqual(
            _html_scripts("popup.html"),
            [
                *self.foundation,
                "plan_lint.js",
                "popup/runtime_client.js",
                "popup/job_state.js",
                "popup/secrets.js",
                "popup/settings_store.js",
                "popup/i18n.js",
                "popup/plan_view.js",
                "popup.js",
            ],
        )
        self.assertEqual(
            _html_scripts("offscreen.html"),
            [*self.foundation, *self.ai_modules, "ai_planner.js", "offscreen.js"],
        )
        self.assertEqual(
            _service_worker_imports(),
            [
                *self.foundation,
                "background/bookmark_api.js",
                "background/snapshot_export.js",
                "background/bookmark_tree.js",
                "background/execution_policy.js",
                "background/undo_log.js",
                "background/action_handlers.js",
                "background/plan_executor.js",
                "background/job_store.js",
                "background/offscreen_client.js",
                "background/job_handlers.js",
                "background/job_lifecycle.js",
                "background/message_router.js",
                *self.ai_modules,
                "ai_planner.js",
            ],
        )

    def test_declared_foundation_chains_load_without_implicit_ordering(self) -> None:
        chains = {
            "popup": _html_scripts("popup.html")[:-1],
            "offscreen": _html_scripts("offscreen.html")[:-1],
            "service_worker": _service_worker_imports(),
        }
        for name, scripts in chains.items():
            with self.subTest(runtime=name):
                script = f"""
                  globalThis.self = globalThis;
                  globalThis.chrome = {{ runtime: {{ getURL: (path) => path, lastError: null }} }};
                  for (const filename of {json.dumps(scripts)}) {{
                    require({json.dumps(str(EXTENSION))} + '/' + filename);
                  }}
                  const root = globalThis.BookmarkAdvisor;
                  console.log(JSON.stringify({{
                    protocol: !!(root && root.Protocol),
                    schema: !!(root && root.PlanSchema),
                    endpoint: !!(root && root.AIEndpoint),
                    paths: !!(root && root.PathUtils),
                    storage: !!(root && root.Storage),
                    actionFacade: typeof globalThis.isExecutableAction === 'function',
                    lint: typeof globalThis.BookmarkPlanLint !== 'undefined',
                    ai: typeof globalThis.BookmarkAdvisorAI !== 'undefined',
                  }}));
                """
                completed = subprocess.run(
                    ["node", "-e", script],
                    cwd=ROOT,
                    check=True,
                    capture_output=True,
                    text=True,
                )
                result = json.loads(completed.stdout.strip().splitlines()[-1])
                for key in ["protocol", "schema", "endpoint", "paths", "storage", "actionFacade"]:
                    self.assertTrue(result[key], (name, key, result))
                self.assertEqual(result["lint"], name == "popup")
                self.assertEqual(result["ai"], name != "popup")

    def test_job_stage_contract_matches_producers_and_popup_labels(self) -> None:
        job_handlers = (EXTENSION / "background" / "job_handlers.js").read_text(encoding="utf-8")
        produced_names = set(
            re.findall(r"setStage\([^,]+,\s*JOB_STAGES\.([A-Z_]+)\)", job_handlers)
        )
        popup_i18n = (EXTENSION / "popup" / "i18n.js").read_text(encoding="utf-8")
        displayed = set(re.findall(r"stage_([a-z_]+):", popup_i18n))
        protocol_script = f"""
          require({json.dumps(str(EXTENSION / 'shared' / 'message_protocol.js'))});
          console.log(JSON.stringify(globalThis.BookmarkAdvisor.Protocol.JOB_STAGES));
        """
        completed = subprocess.run(
            ["node", "-e", protocol_script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        declared_map = json.loads(completed.stdout)
        produced = {declared_map[name] for name in produced_names}
        declared = set(declared_map.values())
        self.assertEqual(produced, declared)
        self.assertLessEqual(produced, displayed)


if __name__ == "__main__":
    unittest.main()
