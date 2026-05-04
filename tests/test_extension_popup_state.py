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

    def _popup_prefix(
        self,
        *,
        lang: str,
        active_job: dict[str, object] | None,
        delay_first_set_callback: bool = False,
    ) -> str:
        storage_seed: dict[str, object] = {"bookmarkAdvisorPreferences": {"lang": lang}}
        if active_job is not None:
            storage_seed["bookmarkAdvisorActiveJob"] = active_job
        active_job_json = "null" if active_job is None else json.dumps(active_job)
        return f"""
        const popupPath = {json.dumps(str(_POPUP))};
        const storageHelpersPath = {json.dumps(str(_STORAGE_HELPERS))};
        const storage = {json.dumps(storage_seed)};
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
          'preferences-tab', 'pref-protect-root', 'pref-sort-order', 'pref-planning-style', 'pref-lang',
          'cancel-job-btn'
        ];
        ids.forEach(element);
        element('api-base-url').value = 'https://api.openai.com/v1';
        element('api-style').value = 'auto';
        element('model').value = 'gpt-4o-mini';
        element('max-actions').value = '40';
        element('focus-path').value = '/收藏夹栏/奇妙小工具';
        element('settings-tab').hidden = true;
        let setCalls = 0;
        let removeCalls = 0;
        let onChangedListener = null;
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
        global.chrome = {{
          runtime: {{
            id: 'popup-test',
            lastError: null,
            sendMessage: (payload, callback) => {{
              if (payload.type === 'get-active-job') {{
                callback({{ job: {active_job_json} }});
                return;
              }}
              if (payload.type === 'cancel-active-job') {{
                callback({{ ok: true }});
                return;
              }}
              callback({{}});
            }}
          }},
          storage: {{ local: {{
            get: (key, callback) => callback({{ [key]: storage[key] }}),
            set: (value, callback) => {{
              setCalls += 1;
              Object.assign(storage, value);
              const shouldDelay = {json.dumps(delay_first_set_callback)} && setCalls === 1;
              if (callback) {{
                if (shouldDelay) {{
                  setTimeout(() => callback(), 0);
                }} else {{
                  callback();
                }}
              }}
            }},
            remove: (key, callback) => {{
              removeCalls += 1;
              if (Array.isArray(key)) {{
                key.forEach((item) => delete storage[item]);
              }} else {{
                delete storage[key];
              }}
              if (callback) callback();
            }}
          }}, onChanged: {{ addListener: (callback) => {{ onChangedListener = callback; }}, removeListener: () => {{}} }} }},
          permissions: {{ contains: (_value, callback) => callback(true), request: (_value, callback) => callback(true) }}
        }};
        require(storageHelpersPath);
        require(popupPath);
        """

    def test_tab_change_persists_even_while_draft_write_is_in_flight(self):
        script = self._popup_prefix(lang="zh", active_job=None, delay_first_set_callback=True) + """
        setTimeout(() => {
          element('settings-tab-btn').click();
          console.log(JSON.stringify({
            activeTab: storage.bookmarkAdvisorPopupDraft.activeTab,
            planHidden: element('plan-tab').hidden,
            settingsHidden: element('settings-tab').hidden,
            setCalls,
          }));
        }, 0);
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["activeTab"], "settings")
        self.assertEqual(result["planHidden"], True)
        self.assertEqual(result["settingsHidden"], False)
        self.assertGreaterEqual(cast(int, result["setCalls"]), 2)

    def test_cancel_click_stays_transient_and_failed_job_shows_localized_cancel_message_en(self):
        script = self._popup_prefix(
            lang="en",
            active_job={"status": "running", "progress": "Working...", "recoverable": True},
        ) + """
        setTimeout(() => {
          const removeCallsBeforeClick = removeCalls;
          element('cancel-job-btn').click();
          setTimeout(() => {
            const afterClick = {
              status: element('status').textContent,
              cancelHidden: element('cancel-job-btn').hidden,
              removeCallsDelta: removeCalls - removeCallsBeforeClick,
              storedActiveJob: Boolean(storage[ACTIVE_JOB_STORAGE_NAME]),
            };
            if (onChangedListener) {
              onChangedListener({
                [ACTIVE_JOB_STORAGE_NAME]: {
                  newValue: {
                    status: 'failed',
                    recoverable: true,
                    error: 'Cancelled by user.',
                    progress: 'Cancelled by user.'
                  }
                }
              }, 'local');
            }
            setTimeout(() => {
              console.log(JSON.stringify({
                afterClick,
              finalStatus: element('status').textContent,
              finalClass: element('status').className,
              finalCancelHidden: element('cancel-job-btn').hidden,
              removeCallsDelta: removeCalls - removeCallsBeforeClick,
            }));
            }, 0);
          }, 0);
        }, 0);
        """
        result = cast(dict[str, object], self._node_script(script))
        after_click = cast(dict[str, object], result["afterClick"])
        self.assertEqual(after_click["status"], "Cancelling...")
        self.assertEqual(after_click["cancelHidden"], True)
        self.assertEqual(after_click["removeCallsDelta"], 0)
        self.assertEqual(after_click["storedActiveJob"], True)
        self.assertEqual(result["finalStatus"], "Background job was cancelled by user.")
        self.assertEqual(result["finalClass"], "error")
        self.assertEqual(result["finalCancelHidden"], True)
        self.assertEqual(result["removeCallsDelta"], 0)

    def test_cancel_click_stays_transient_and_failed_job_shows_localized_cancel_message_zh(self):
        script = self._popup_prefix(
            lang="zh",
            active_job={"status": "running", "progress": "Working...", "recoverable": True},
        ) + """
        setTimeout(() => {
          const removeCallsBeforeClick = removeCalls;
          element('cancel-job-btn').click();
          setTimeout(() => {
            const afterClick = {
              status: element('status').textContent,
              cancelHidden: element('cancel-job-btn').hidden,
              removeCallsDelta: removeCalls - removeCallsBeforeClick,
              storedActiveJob: Boolean(storage[ACTIVE_JOB_STORAGE_NAME]),
            };
            if (onChangedListener) {
              onChangedListener({
                [ACTIVE_JOB_STORAGE_NAME]: {
                  newValue: {
                    status: 'failed',
                    recoverable: true,
                    error: 'Cancelled by user.',
                    progress: 'Cancelled by user.'
                  }
                }
              }, 'local');
            }
            setTimeout(() => {
              console.log(JSON.stringify({
                afterClick,
              finalStatus: element('status').textContent,
              finalClass: element('status').className,
              finalCancelHidden: element('cancel-job-btn').hidden,
              removeCallsDelta: removeCalls - removeCallsBeforeClick,
            }));
            }, 0);
          }, 0);
        }, 0);
        """
        result = cast(dict[str, object], self._node_script(script))
        after_click = cast(dict[str, object], result["afterClick"])
        self.assertEqual(after_click["status"], "正在终止...")
        self.assertEqual(after_click["cancelHidden"], True)
        self.assertEqual(after_click["removeCallsDelta"], 0)
        self.assertEqual(after_click["storedActiveJob"], True)
        self.assertEqual(result["finalStatus"], "后台任务已被用户取消。")
        self.assertEqual(result["finalClass"], "error")
        self.assertEqual(result["finalCancelHidden"], True)
        self.assertEqual(result["removeCallsDelta"], 0)


if __name__ == "__main__":
    _ = unittest.main()
