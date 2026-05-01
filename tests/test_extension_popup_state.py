"""Extension popup UI state persistence tests."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import cast


_REPO_ROOT = Path(__file__).resolve().parent.parent
_POPUP = _REPO_ROOT / "extension" / "popup.js"
_STORAGE_HELPERS = _REPO_ROOT / "extension" / "storage_helpers.js"


@unittest.skipUnless(shutil.which("node"), "node is required for extension JS popup tests")
class ExtensionPopupStateTest(unittest.TestCase):
    def _node_script(self, body: str) -> object:
        completed = subprocess.run(
            ["node", "-e", body],
            check=True,
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
        )
        return cast(object, json.loads(completed.stdout))

    def test_tab_change_persists_even_while_draft_write_is_in_flight(self):
        script = f"""
        const popupPath = {json.dumps(str(_POPUP))};
        const storageHelpersPath = {json.dumps(str(_STORAGE_HELPERS))};
        const storage = {{}};
        const elements = new Map();
        class Element {{
          constructor(id) {{
            this.id = id;
            this.value = '';
            this.hidden = false;
            this.disabled = false;
            this.textContent = '';
            this.className = '';
            this.listeners = {{}};
            this.classList = {{ toggle: () => {{}} }};
          }}
          addEventListener(type, callback) {{ this.listeners[type] = callback; }}
          setAttribute() {{}}
          appendChild() {{}}
          click() {{ if (this.listeners.click) this.listeners.click({{ target: this }}); }}
        }}
        function element(id) {{
          if (!elements.has(id)) elements.set(id, new Element(id));
          return elements.get(id);
        }}
        const ids = [
          'plan-file', 'api-key', 'api-base-url', 'api-style', 'endpoint-preview',
          'key-storage-status', 'model', 'request-timeout', 'max-actions', 'focus-path', 'user-instruction',
          'status', 'stats', 'total-count', 'executable-count', 'review-count',
          'error-count', 'warning-count', 'preview-list', 'execute-btn',
          'export-snapshot-btn', 'generate-ai-btn', 'revise-ai-btn', 'save-credentials-btn',
          'forget-key-btn', 'download-report-btn', 'spinner', 'plan-tab-btn',
          'settings-tab-btn', 'preferences-tab-btn', 'plan-tab', 'settings-tab',
          'preferences-tab', 'pref-protect-root', 'pref-sort-order', 'pref-planning-style', 'pref-lang'
        ];
        ids.forEach(element);
        element('api-base-url').value = 'https://api.openai.com/v1';
        element('api-style').value = 'auto';
        element('model').value = 'gpt-4o-mini';
        element('max-actions').value = '40';
        element('focus-path').value = '/收藏夹栏/奇妙小工具';
        element('settings-tab').hidden = true;
        global.BookmarkPlanLint = {{ parsePlanText: () => ({{}}), lintPlan: () => ({{ ok: true, errors: [], warnings: [], executableActions: [], reviewActions: [], totalActions: 0 }}), formatDiagnostic: () => '', resolveActionStatus: () => 'approved' }};
        global.window = {{ addEventListener: () => {{}} }};
        global.document = {{
          visibilityState: 'visible',
          addEventListener: () => {{}},
          createElement: () => new Element('created'),
          getElementById: element
        }};
        global.URL = URL;
        global.Blob = function () {{}};
        let setCalls = 0;
        global.chrome = {{
          runtime: {{ id: 'popup-test', lastError: null, sendMessage: () => {{}} }},
          storage: {{ local: {{
            get: (key, callback) => callback({{ [key]: storage[key] }}),
            set: (value, callback) => {{
              setCalls += 1;
              Object.assign(storage, value);
              if (setCalls > 1 && callback) callback();
            }},
            remove: (key, callback) => {{ delete storage[key]; if (callback) callback(); }}
          }}, onChanged: {{ addListener: () => {{}}, removeListener: () => {{}} }} }},
          permissions: {{ contains: (_value, callback) => callback(true), request: (_value, callback) => callback(true) }}
        }};
        require(storageHelpersPath);
        require(popupPath);
        setTimeout(() => {{
          element('settings-tab-btn').click();
          console.log(JSON.stringify({{
            activeTab: storage.bookmarkAdvisorPopupDraft.activeTab,
            planHidden: element('plan-tab').hidden,
            settingsHidden: element('settings-tab').hidden,
            setCalls
          }}));
        }}, 0);
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["activeTab"], "settings")
        self.assertEqual(result["planHidden"], True)
        self.assertEqual(result["settingsHidden"], False)
        self.assertGreaterEqual(cast(int, result["setCalls"]), 2)


if __name__ == "__main__":
    _ = unittest.main()
