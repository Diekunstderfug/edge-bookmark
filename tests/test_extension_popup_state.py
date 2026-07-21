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
_ACTION_CONSTANTS = _REPO_ROOT / "extension" / "action_constants.js"


@unittest.skipUnless(shutil.which("node"), "node is required for extension JS popup tests")
class ExtensionPopupStateTest(unittest.TestCase):
    def _node_script(self, body: str) -> object:
        try:
            completed = subprocess.run(
                ["node", "-e", body],
                check=True,
                capture_output=True,
                text=True,
                cwd=_REPO_ROOT,
                timeout=15,
            )
        except subprocess.TimeoutExpired as exc:
            self.fail(
                "Node popup test timed out after 15 seconds.\n"
                f"stdout:\n{exc.stdout or ''}\n"
                f"stderr:\n{exc.stderr or ''}"
            )
        except subprocess.CalledProcessError as exc:
            self.fail(
                f"Node popup test failed with exit code {exc.returncode}.\n"
                f"stdout:\n{exc.stdout or ''}\n"
                f"stderr:\n{exc.stderr or ''}"
            )
        try:
            return cast(object, json.loads(completed.stdout))
        except json.JSONDecodeError as exc:
            self.fail(
                f"Node popup test did not emit valid JSON: {exc}\n"
                f"stdout:\n{completed.stdout}\n"
                f"stderr:\n{completed.stderr}"
            )

    def _popup_prefix(
        self,
        *,
        lang: str,
        active_job: dict[str, object] | None,
        ui_draft: dict[str, object] | None = None,
        delay_first_set_callback: bool = False,
        include_session_storage: bool = True,
    ) -> str:
        storage_seed: dict[str, object] = {"bookmarkAdvisorPreferences": {"lang": lang}}
        if active_job is not None:
            storage_seed["bookmarkAdvisorActiveJob"] = active_job
        if ui_draft is not None:
            storage_seed["bookmarkAdvisorPopupDraft"] = ui_draft
        active_job_json = "null" if active_job is None else json.dumps(active_job)
        session_storage_js = "" if not include_session_storage else """, session: {
            get: (key, callback) => callback({ [key]: sessionStorage[key] }),
            set: (value, callback) => { Object.assign(sessionStorage, value); if (callback) callback(); },
            remove: (key, callback) => {
              if (Array.isArray(key)) {
                key.forEach((item) => delete sessionStorage[item]);
              } else {
                delete sessionStorage[key];
              }
              if (callback) callback();
            }
          }"""
        return f"""
        const popupPath = {json.dumps(str(_POPUP))};
        const storageHelpersPath = {json.dumps(str(_STORAGE_HELPERS))};
        const actionConstantsPath = {json.dumps(str(_ACTION_CONSTANTS))};
        const storage = {json.dumps(storage_seed)};
        const sessionStorage = {{}};
        const elements = new Map();
        class Element {{
          constructor(id) {{
            this.id = id;
            this.value = '';
            this.hidden = false;
            this.disabled = false;
            this._textContent = '';
            this.className = '';
            this.children = [];
            this.attributes = {{}};
            this.style = {{}};
            this.listeners = {{}};
            this.classList = {{
              add: (...names) => names.forEach((name) => this._setClass(name, true)),
              remove: (...names) => names.forEach((name) => this._setClass(name, false)),
              contains: (name) => this.className.split(/\\s+/).includes(name),
              toggle: (name, force) => {{
                const shouldAdd = force === undefined ? !this.classList.contains(name) : Boolean(force);
                this._setClass(name, shouldAdd);
                return shouldAdd;
              }},
            }};
          }}
          get textContent() {{
            return [this._textContent, ...this.children.map((child) => child.textContent)].join('');
          }}
          set textContent(value) {{ this._textContent = String(value); }}
          set innerHTML(_value) {{ this.children = []; this._textContent = ''; }}
          get innerHTML() {{ return this.textContent; }}
          _setClass(name, shouldAdd) {{
            const classes = new Set(this.className.split(/\\s+/).filter(Boolean));
            if (shouldAdd) classes.add(name); else classes.delete(name);
            this.className = Array.from(classes).join(' ');
          }}
          addEventListener(type, callback) {{ this.listeners[type] = callback; }}
          setAttribute(name, value) {{ this.attributes[name] = String(value); }}
          appendChild(child) {{ this.children.push(child); return child; }}
          click() {{ if (this.listeners.click) this.listeners.click({{ target: this }}); }}
          focus() {{}}
          blur() {{ if (this.listeners.blur) this.listeners.blur(); }}
        }}
        function element(id) {{
          if (!elements.has(id)) elements.set(id, new Element(id));
          return elements.get(id);
        }}
        const ids = [
          'plan-file', 'api-key', 'api-base-url', 'api-style', 'endpoint-preview',
          'key-storage-status', 'model', 'request-timeout', 'max-retries', 'max-actions', 'focus-path', 'user-instruction',
          'status', 'stats', 'total-count', 'executable-count', 'review-count',
          'error-count', 'warning-count', 'preview-list', 'execute-btn',
          'export-snapshot-btn', 'generate-ai-btn', 'revise-ai-btn', 'save-credentials-btn',
          'forget-key-btn', 'download-report-btn', 'undo-btn', 'continue-btn', 'spinner',
          'organize-tab-btn', 'ai-service-tab-btn', 'strategy-tab-btn',
          'diagnostics-tab-btn', 'organize-tab', 'ai-service-tab', 'strategy-tab',
          'diagnostics-tab', 'pref-protect-root', 'pref-sort-order',
          'pref-planning-style', 'pref-lang', 'cancel-job-btn'
        ];
        ids.forEach(element);
        element('api-base-url').value = 'https://api.openai.com/v1';
        element('api-style').value = 'auto';
        element('model').value = 'gpt-5.4-mini';
        element('max-actions').value = '40';
        element('focus-path').value = '/收藏夹栏/奇妙小工具';
        element('ai-service-tab').hidden = true;
        element('strategy-tab').hidden = true;
        element('diagnostics-tab').hidden = true;
        let setCalls = 0;
        let removeCalls = 0;
        let onChangedListener = null;
        global.BookmarkPlanLint = {{ parsePlanText: () => ({{}}), lintPlan: () => ({{ ok: true, errors: [], warnings: [], executableActions: [], reviewActions: [], totalActions: 0 }}), formatDiagnostic: () => '', resolveActionStatus: () => 'approved' }};
        global.window = {{ addEventListener: () => {{}} }};
        global.document = {{
          visibilityState: 'visible',
          addEventListener: () => {{}},
          createElement: () => new Element('created'),
          getElementById: element,
          querySelectorAll: () => []
        }};
        global.URL = URL;
        global.Blob = function () {{}};
        function waitFor(predicate, deadlineMs = 1000) {{
          const startedAt = Date.now();
          return new Promise((resolve, reject) => {{
            const tick = () => {{
              try {{
                if (predicate()) {{
                  resolve();
                  return;
                }}
              }} catch (error) {{
                reject(error);
                return;
              }}
              if (Date.now() - startedAt >= deadlineMs) {{
                reject(new Error('waitFor deadline exceeded'));
                return;
              }}
              setTimeout(tick, 1);
            }};
            tick();
          }});
        }}
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
          }}{session_storage_js}, onChanged: {{ addListener: (callback) => {{ onChangedListener = callback; }}, removeListener: () => {{}} }} }},
          permissions: {{ contains: (_value, callback) => callback(true), request: (_value, callback) => callback(true) }}
        }};
        require(storageHelpersPath);
        require(actionConstantsPath);
        require(popupPath);
        """

    def test_tab_change_persists_even_while_draft_write_is_in_flight(self):
        script = self._popup_prefix(lang="zh", active_job=None, delay_first_set_callback=True) + """
        (async () => {
          await waitFor(() => storage.bookmarkAdvisorPopupDraft, 1000);
          element('ai-service-tab-btn').click();
          await waitFor(() => storage.bookmarkAdvisorPopupDraft.activeTab === 'ai-service', 1000);
          console.log(JSON.stringify({
            activeTab: storage.bookmarkAdvisorPopupDraft.activeTab,
            organizeHidden: element('organize-tab').hidden,
            aiServiceHidden: element('ai-service-tab').hidden,
            strategyHidden: element('strategy-tab').hidden,
            diagnosticsHidden: element('diagnostics-tab').hidden,
            setCalls,
          }));
        })().catch((error) => {
          console.error(error && error.stack ? error.stack : error);
          process.exit(1);
        });
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["activeTab"], "ai-service")
        self.assertEqual(result["organizeHidden"], True)
        self.assertEqual(result["aiServiceHidden"], False)
        self.assertEqual(result["strategyHidden"], True)
        self.assertEqual(result["diagnosticsHidden"], True)
        self.assertGreaterEqual(cast(int, result["setCalls"]), 2)

    def test_old_active_tab_values_restore_new_sections(self):
        cases = [
            ("plan", "organize"),
            ("settings", "ai-service"),
            ("preferences", "strategy"),
        ]
        for old_tab, expected_tab in cases:
            with self.subTest(old_tab=old_tab):
                script = self._popup_prefix(
                    lang="en",
                    active_job=None,
                    ui_draft={
                        "version": 2,
                        "activeTab": old_tab,
                        "apiBaseUrl": "https://api.openai.com/v1",
                        "apiStyle": "auto",
                        "model": "gpt-5.4-mini",
                        "requestTimeout": "180",
                        "focusPath": "",
                        "maxActions": "40",
                        "maxRetries": "1",
                        "userInstruction": "",
                        "updated_at": "2026-06-21T00:00:00.000Z",
                    },
                ) + """
                (async () => {
                  await waitFor(() => element('pref-lang').value === 'en', 1000);
                  console.log(JSON.stringify({
                    organizeHidden: element('organize-tab').hidden,
                    aiServiceHidden: element('ai-service-tab').hidden,
                    strategyHidden: element('strategy-tab').hidden,
                    diagnosticsHidden: element('diagnostics-tab').hidden,
                    organizeSelected: element('organize-tab-btn').attributes['aria-selected'],
                    aiServiceSelected: element('ai-service-tab-btn').attributes['aria-selected'],
                    strategySelected: element('strategy-tab-btn').attributes['aria-selected'],
                    diagnosticsSelected: element('diagnostics-tab-btn').attributes['aria-selected']
                  }));
                })().catch((error) => {
                  console.error(error && error.stack ? error.stack : error);
                  process.exit(1);
                });
                """
                result = cast(dict[str, object], self._node_script(script))
                self.assertEqual(result["organizeHidden"], expected_tab != "organize")
                self.assertEqual(result["aiServiceHidden"], expected_tab != "ai-service")
                self.assertEqual(result["strategyHidden"], expected_tab != "strategy")
                self.assertEqual(result["diagnosticsHidden"], expected_tab != "diagnostics")
                self.assertEqual(result["organizeSelected"], str(expected_tab == "organize").lower())
                self.assertEqual(result["aiServiceSelected"], str(expected_tab == "ai-service").lower())
                self.assertEqual(result["strategySelected"], str(expected_tab == "strategy").lower())
                self.assertEqual(result["diagnosticsSelected"], str(expected_tab == "diagnostics").lower())

    def test_four_config_tabs_switch_and_persist(self):
        script = self._popup_prefix(lang="en", active_job=None) + """
        (async () => {
          await waitFor(() => storage.bookmarkAdvisorPopupDraft, 1000);
          element('diagnostics-tab-btn').click();
          await waitFor(() => storage.bookmarkAdvisorPopupDraft.activeTab === 'diagnostics', 1000);
          console.log(JSON.stringify({
            activeTab: storage.bookmarkAdvisorPopupDraft.activeTab,
            organizeHidden: element('organize-tab').hidden,
            aiServiceHidden: element('ai-service-tab').hidden,
            strategyHidden: element('strategy-tab').hidden,
            diagnosticsHidden: element('diagnostics-tab').hidden,
            diagnosticsSelected: element('diagnostics-tab-btn').attributes['aria-selected']
          }));
        })().catch((error) => {
          console.error(error && error.stack ? error.stack : error);
          process.exit(1);
        });
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(
            result,
            {
                "activeTab": "diagnostics",
                "organizeHidden": True,
                "aiServiceHidden": True,
                "strategyHidden": True,
                "diagnosticsHidden": False,
                "diagnosticsSelected": "true",
            },
        )

    def test_api_key_draft_is_stored_in_session_not_local(self):
        # API key 草稿仅在失焦时加密落盘(P1-3:不再在每次按键时持久化)
        script = self._popup_prefix(lang="en", active_job=None) + """
        (async () => {
          await waitFor(() => element('api-key').listeners.blur && element('pref-lang').value === 'en', 1000);
          element('api-key').value = 'draft-key';
          element('api-key').blur();
          await waitFor(() => sessionStorage.bookmarkAdvisorOpenAIKeyDraft, 1000);
          console.log(JSON.stringify({
            hasSessionDraft: Boolean(sessionStorage.bookmarkAdvisorOpenAIKeyDraft),
            hasLocalDraft: Boolean(storage.bookmarkAdvisorOpenAIKeyDraft)
          }));
        })().catch((error) => {
          console.error(error && error.stack ? error.stack : error);
          process.exit(1);
        });
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result, {"hasSessionDraft": True, "hasLocalDraft": False})

    def test_api_key_draft_local_fallback_is_preserved_without_session_storage(self):
        script = self._popup_prefix(lang="en", active_job=None, include_session_storage=False) + """
        (async () => {
          await waitFor(() => element('api-key').listeners.blur && element('pref-lang').value === 'en', 1000);
          element('api-key').value = 'draft-key';
          element('api-key').blur();
          await waitFor(() => storage.bookmarkAdvisorOpenAIKeyDraft, 1000);
          console.log(JSON.stringify({
            hasLocalDraft: Boolean(storage.bookmarkAdvisorOpenAIKeyDraft)
          }));
        })().catch((error) => {
          console.error(error && error.stack ? error.stack : error);
          process.exit(1);
        });
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result, {"hasLocalDraft": True})

    def test_api_key_not_persisted_on_keystroke_only_on_blur(self):
        # P1-3 回归:输入 key 但未失焦时,草稿不应落盘(避免"粘贴后未保存即落盘"的语义混淆)
        script = self._popup_prefix(lang="en", active_job=None) + """
        (async () => {
          await waitFor(() => element('api-key').listeners.blur && element('pref-lang').value === 'en', 1000);
          element('api-key').value = 'draft-key';
          // 仅触发 input 监听(若有),不触发 blur
          if (element('api-key').listeners.input) {
            element('api-key').listeners.input({ target: element('api-key') });
          }
          // 给异步写入一点时间,确认 key 草稿确实未落盘
          await new Promise((resolve) => setTimeout(resolve, 100));
          console.log(JSON.stringify({
            hasSessionDraft: Boolean(sessionStorage.bookmarkAdvisorOpenAIKeyDraft),
            hasLocalDraft: Boolean(storage.bookmarkAdvisorOpenAIKeyDraft)
          }));
        })().catch((error) => {
          console.error(error && error.stack ? error.stack : error);
          process.exit(1);
        });
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result, {"hasSessionDraft": False, "hasLocalDraft": False})

    def test_endpoint_preview_matches_actual_auto_fallback_order(self):
        script = self._popup_prefix(lang="en", active_job=None) + """
        (async () => {
          await waitFor(() => element('endpoint-preview').textContent.includes('/chat/completions'), 1000);
          console.log(JSON.stringify({
            preview: element('endpoint-preview').textContent
          }));
        })().catch((error) => {
          console.error(error && error.stack ? error.stack : error);
          process.exit(1);
        });
        """
        result = cast(dict[str, object], self._node_script(script))
        preview = cast(str, result["preview"])
        self.assertIn("/chat/completions, then https://api.openai.com/v1/completions, then https://api.openai.com/v1/responses", preview)
        self.assertNotIn("/responses, https://api.openai.com/v1/chat/completions", preview)

    def test_save_warns_when_endpoint_is_third_party(self):
        # P0-3:apiBaseUrl 非 api.openai.com 时,保存凭证应附加安全警告(不阻断保存)。
        # 走无 key 的 else 分支,避免依赖 crypto.subtle。
        script = self._popup_prefix(lang="en", active_job=None) + """
        (async () => {
          await waitFor(() => element('save-credentials-btn').listeners.click && element('pref-lang').value === 'en', 1000);
          element('api-base-url').value = 'https://evil.example.com/v1';
          element('api-key').value = '';
          element('save-credentials-btn').click();
          await waitFor(() => element('key-storage-status').textContent.includes('evil.example.com'), 1000);
          console.log(JSON.stringify({
            status: element('key-storage-status').textContent,
            className: element('key-storage-status').className,
          }));
        })().catch((error) => {
          console.error(error && error.stack ? error.stack : error);
          process.exit(1);
        });
        """
        result = cast(dict[str, object], self._node_script(script))
        status = cast(str, result["status"])
        self.assertIn("evil.example.com", status)
        self.assertIn("Only trust endpoints", status)
        # 第三方端点应显示为 warning 而非 ok
        self.assertIn("warning", cast(str, result["className"]))

    def test_save_no_warning_for_official_endpoint(self):
        # 对照:api.openai.com 不应触发第三方警告
        script = self._popup_prefix(lang="en", active_job=None) + """
        (async () => {
          await waitFor(() => element('save-credentials-btn').listeners.click && element('pref-lang').value === 'en', 1000);
          element('api-base-url').value = 'https://api.openai.com/v1';
          element('api-key').value = '';
          element('save-credentials-btn').click();
          await waitFor(() => element('key-storage-status').textContent.includes('Paste an API key'), 1000);
          console.log(JSON.stringify({
            status: element('key-storage-status').textContent,
          }));
        })().catch((error) => {
          console.error(error && error.stack ? error.stack : error);
          process.exit(1);
        });
        """
        result = cast(dict[str, object], self._node_script(script))
        status = cast(str, result["status"])
        self.assertNotIn("Only trust endpoints", status)
        self.assertNotIn("Heads-up", status)

    def test_cancel_click_stays_transient_and_failed_job_shows_localized_cancel_message_en(self):
        script = self._popup_prefix(
            lang="en",
            active_job={"status": "running", "progress": "Working...", "recoverable": True},
        ) + """
        (async () => {
          await waitFor(() =>
            element('pref-lang').value === 'en' &&
            element('cancel-job-btn').listeners.click,
            1000
          );
          const removeCallsBeforeClick = removeCalls;
          element('cancel-job-btn').click();
          await waitFor(() => element('status').textContent === 'Cancelling...', 1000);
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
          await waitFor(() => element('status').textContent === 'Background job was cancelled by user.', 1000);
          console.log(JSON.stringify({
            afterClick,
              finalStatus: element('status').textContent,
              finalClass: element('status').className,
              finalCancelHidden: element('cancel-job-btn').hidden,
              removeCallsDelta: removeCalls - removeCallsBeforeClick,
          }));
        })().catch((error) => {
          console.error(error && error.stack ? error.stack : error);
          process.exit(1);
        });
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

    def test_keep_for_review_preview_uses_human_title_not_raw_action_type(self):
        plan = {
            "actions": [
                {
                    "action_id": "review-1",
                    "action_type": "keep_for_review",
                    "status": "pending",
                    "confidence": 0.25,
                }
            ]
        }
        script = self._popup_prefix(lang="en", active_job=None) + f"""
        (async () => {{
          await waitFor(() => element('plan-file').listeners.change && element('pref-lang').value === 'en', 1000);
          const plan = {json.dumps(plan)};
          BookmarkPlanLint.parsePlanText = (text) => JSON.parse(text);
          BookmarkPlanLint.lintPlan = (loadedPlan) => ({{
            ok: true,
            errors: [],
            warnings: [],
            executableActions: [],
            reviewActions: loadedPlan.actions,
            totalActions: loadedPlan.actions.length,
          }});
          await element('plan-file').listeners.change({{
            target: {{ files: [{{ text: async () => JSON.stringify(plan) }}] }}
          }});
          console.log(JSON.stringify({{
            previewText: element('preview-list').textContent,
            reviewCount: element('review-count').textContent,
          }}));
        }})().catch((error) => {{
          console.error(error && error.stack ? error.stack : error);
          process.exit(1);
        }});
        """
        result = cast(dict[str, object], self._node_script(script))
        preview_text = cast(str, result["previewText"])
        self.assertIn("Needs review", preview_text)
        self.assertIn("Review item", preview_text)
        self.assertNotIn("keep_for_review", preview_text)
        self.assertEqual(result["reviewCount"], "1")

    def test_cancel_click_stays_transient_and_failed_job_shows_localized_cancel_message_zh(self):
        script = self._popup_prefix(
            lang="zh",
            active_job={"status": "running", "progress": "Working...", "recoverable": True},
        ) + """
        (async () => {
          await waitFor(() =>
            element('pref-lang').value === 'zh' &&
            element('cancel-job-btn').listeners.click,
            1000
          );
          const removeCallsBeforeClick = removeCalls;
          element('cancel-job-btn').click();
          await waitFor(() => element('status').textContent === '正在终止...', 1000);
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
          await waitFor(() => element('status').textContent === '后台任务已被用户取消。', 1000);
          console.log(JSON.stringify({
            afterClick,
              finalStatus: element('status').textContent,
              finalClass: element('status').className,
              finalCancelHidden: element('cancel-job-btn').hidden,
              removeCallsDelta: removeCalls - removeCallsBeforeClick,
          }));
        })().catch((error) => {
          console.error(error && error.stack ? error.stack : error);
          process.exit(1);
        });
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
