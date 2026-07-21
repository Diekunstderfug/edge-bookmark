"""Independent tests for popup settings persistence and host permissions."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"


class ExtensionPopupSettingsStoreTest(unittest.TestCase):
    def _node_eval(self, body: str) -> Any:
        script = f"""
          require({json.dumps(str(EXTENSION / 'shared' / 'message_protocol.js'))});
          require({json.dumps(str(EXTENSION / 'shared' / 'ai_endpoint.js'))});
          require({json.dumps(str(EXTENSION / 'popup' / 'settings_store.js'))});

          const protocol = BookmarkAdvisor.Protocol;
          const aiEndpoint = BookmarkAdvisor.AIEndpoint;
          const localState = {{}};
          const syncState = {{}};
          const storageCalls = [];
          const permissionCalls = [];
          let syncGetError = '';
          let syncSetError = '';
          let containsGranted = false;
          let requestGranted = false;
          const clone = (value) => value === undefined ? undefined : structuredClone(value);
          const chrome = {{
            runtime: {{ lastError: null }},
            storage: {{
              local: {{
                get(key, callback) {{
                  storageCalls.push(['local.get', key]);
                  callback({{ [key]: clone(localState[key]) }});
                }},
                set(value, callback) {{
                  storageCalls.push(['local.set', Object.keys(value)[0], clone(Object.values(value)[0])]);
                  Object.assign(localState, clone(value));
                  callback();
                }},
              }},
              sync: {{
                get(key, callback) {{
                  storageCalls.push(['sync.get', key]);
                  if (syncGetError) chrome.runtime.lastError = {{ message: syncGetError }};
                  callback({{ [key]: clone(syncState[key]) }});
                  chrome.runtime.lastError = null;
                }},
                set(value, callback) {{
                  storageCalls.push(['sync.set', Object.keys(value)[0], clone(Object.values(value)[0])]);
                  if (syncSetError) chrome.runtime.lastError = {{ message: syncSetError }};
                  if (!syncSetError) Object.assign(syncState, clone(value));
                  callback();
                  chrome.runtime.lastError = null;
                }},
              }},
            }},
            permissions: {{
              contains(value, callback) {{
                permissionCalls.push(['contains', clone(value)]);
                callback(containsGranted);
              }},
              request(value, callback) {{
                permissionCalls.push(['request', clone(value)]);
                callback(requestGranted);
              }},
            }},
          }};
          const store = BookmarkAdvisor.Popup.SettingsStore.create({{
            chrome, protocol, aiEndpoint,
          }});

          (async () => {{
            {body}
          }})().catch((error) => {{
            process.stderr.write(error && error.stack ? error.stack : String(error));
            process.exit(1);
          }});
        """
        completed = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        output = completed.stdout.strip().splitlines()
        self.assertTrue(output, completed.stderr)
        return json.loads(output[-1])

    def test_defaults_and_normalizers_preserve_string_and_tab_contracts(self) -> None:
        result = self._node_eval(
            """
            let invalidUrlError = '';
            let insecureUrlError = '';
            try { store.normalizeLlmSettings({ apiBaseUrl: 'not a URL' }); }
            catch (error) { invalidUrlError = error.message; }
            try { store.normalizeHttpsBaseUrl('http://api.example.com/v1'); }
            catch (error) { insecureUrlError = error.message; }

            const normalizedLlm = store.normalizeLlmSettings({
              apiBaseUrl: '  https://api.example.com/v1/?query=ignored#fragment  ',
              apiStyle: 'invalid-style',
              model: '  custom-model  ',
              requestTimeout: 120,
            });
            const zeroTimeouts = [
              store.normalizeLlmSettings({ requestTimeout: 0 }).requestTimeout,
              store.normalizeLlmSettings({ requestTimeout: '0' }).requestTimeout,
            ];
            const normalizedDraft = store.normalizeUiDraft({
              activeTab: 'unknown-tab',
              apiBaseUrl: 'not-normalized-on-purpose',
              apiStyle: 'invalid-style',
              model: 123,
              requestTimeout: 60,
              focusPath: 123,
              maxActions: 55,
              maxRetries: 2,
              userInstruction: false,
            });
            const aliases = ['plan', 'settings', 'preferences', 'diagnostics', '', 'bad'].map(
              (name) => store.normalizeActiveTabName(name),
            );
            const normalizedPreferences = store.normalizePreferences({
              protectRootLooseBookmarks: 'no',
              sortOrder: 'bad',
              planningStyle: 'aggressive',
              lang: 'fr',
            });
            console.log(JSON.stringify({
              defaults: store.defaults,
              loadedDefaults: {
                llm: await store.loadLlmSettings(),
                draft: await store.loadUiDraft(),
                preferences: await store.loadPreferences(),
              },
              normalizedLlm,
              zeroTimeouts,
              normalizedDraft,
              aliases,
              normalizedPreferences,
              normalizedEmptyUrl: store.normalizeHttpsBaseUrl(''),
              invalidUrlError,
              insecureUrlError,
            }));
            """
        )
        default_llm = {
            "apiBaseUrl": "https://api.openai.com/v1",
            "apiStyle": "auto",
            "model": "gpt-5.4-mini",
            "requestTimeout": "180",
        }
        default_draft = {
            "activeTab": "organize",
            "focusPath": "",
            "maxActions": "40",
            "maxRetries": "",
        }
        default_preferences = {
            "protectRootLooseBookmarks": "yes",
            "sortOrder": "none",
            "planningStyle": "balanced",
            "lang": "en",
        }
        self.assertEqual(result["defaults"]["llmSettings"], default_llm)
        self.assertEqual(result["defaults"]["uiDraft"], default_draft)
        self.assertEqual(result["defaults"]["preferences"], default_preferences)
        self.assertEqual(result["loadedDefaults"], {
            "llm": default_llm,
            "draft": default_draft,
            "preferences": default_preferences,
        })
        self.assertEqual(result["normalizedLlm"], {
            "apiBaseUrl": "https://api.example.com/v1",
            "apiStyle": "auto",
            "model": "custom-model",
            "requestTimeout": "120",
        })
        self.assertEqual(result["zeroTimeouts"], ["180", "0"])
        self.assertEqual(result["normalizedDraft"], {
            "activeTab": "organize",
            "apiBaseUrl": "not-normalized-on-purpose",
            "apiStyle": "invalid-style",
            "model": "",
            "requestTimeout": "180",
            "focusPath": "",
            "maxActions": "40",
            "maxRetries": "",
            "userInstruction": "",
        })
        self.assertEqual(
            result["aliases"],
            ["organize", "ai-service", "strategy", "diagnostics", "organize", "organize"],
        )
        self.assertEqual(result["normalizedPreferences"], {
            "protectRootLooseBookmarks": "no",
            "sortOrder": "none",
            "planningStyle": "aggressive",
            "lang": "en",
        })
        self.assertEqual(result["normalizedEmptyUrl"], "")
        self.assertEqual(result["invalidUrlError"], "API base URL must be a valid https:// URL.")
        self.assertEqual(result["insecureUrlError"], "API base URL must use https://.")

    def test_roundtrip_uses_protocol_keys_and_sync_preferences(self) -> None:
        result = self._node_eval(
            """
            const savedLlm = await store.saveLlmSettings({
              apiBaseUrl: 'https://provider.example/v1/',
              apiStyle: 'responses',
              model: '  model-x ',
              requestTimeout: ' 240 ',
            });
            const savedDraft = await store.saveUiDraft({
              version: 2,
              activeTab: 'settings',
              apiBaseUrl: 'https://provider.example/v1',
              apiStyle: 'responses',
              model: 'model-x',
              requestTimeout: '240',
              focusPath: '/收藏夹栏/AI',
              maxActions: '55',
              maxRetries: '2',
              userInstruction: 'Keep docs together',
              updated_at: '2026-07-10T08:00:00.000Z',
            });
            const savedPreferences = await store.savePreferences({
              protectRootLooseBookmarks: 'no',
              sortOrder: 'alpha-desc',
              planningStyle: 'conservative',
              lang: 'zh',
            });
            console.log(JSON.stringify({
              savedLlm,
              loadedLlm: await store.loadLlmSettings(),
              savedDraft,
              storedDraft: localState[protocol.STORAGE_KEYS.POPUP_DRAFT],
              loadedDraft: await store.loadUiDraft(),
              savedPreferences,
              loadedPreferences: await store.loadPreferences(),
              localKeys: Object.keys(localState).sort(),
              syncKeys: Object.keys(syncState).sort(),
              storageCalls,
            }));
            """
        )
        llm = {
            "apiBaseUrl": "https://provider.example/v1",
            "apiStyle": "responses",
            "model": "model-x",
            "requestTimeout": "240",
        }
        self.assertEqual(result["savedLlm"], llm)
        self.assertEqual(result["loadedLlm"], llm)
        self.assertEqual(result["savedDraft"]["version"], 3)
        self.assertEqual(result["savedDraft"]["activeTab"], "ai-service")
        self.assertEqual(result["savedDraft"]["updated_at"], "2026-07-10T08:00:00.000Z")
        self.assertEqual(result["storedDraft"], result["savedDraft"])
        self.assertNotIn("version", result["loadedDraft"])
        self.assertNotIn("updated_at", result["loadedDraft"])
        self.assertEqual(result["loadedDraft"]["activeTab"], "ai-service")
        self.assertEqual(result["loadedDraft"]["maxRetries"], "2")
        preferences = {
            "protectRootLooseBookmarks": "no",
            "sortOrder": "alpha-desc",
            "planningStyle": "conservative",
            "lang": "zh",
        }
        self.assertEqual(result["savedPreferences"], preferences)
        self.assertEqual(result["loadedPreferences"], preferences)
        self.assertEqual(
            result["localKeys"],
            ["bookmarkAdvisorLlmSettings", "bookmarkAdvisorPopupDraft"],
        )
        self.assertEqual(result["syncKeys"], ["bookmarkAdvisorPreferences"])

    def test_load_merges_partial_records_and_preserves_ui_raw_strings(self) -> None:
        result = self._node_eval(
            """
            localState[protocol.STORAGE_KEYS.LLM_SETTINGS] = { model: '  custom-model  ' };
            localState[protocol.STORAGE_KEYS.POPUP_DRAFT] = {
              version: 2,
              activeTab: 'preferences',
              apiBaseUrl: 'draft://raw-value',
              apiStyle: 'raw-style',
              requestTimeout: '0',
              maxRetries: '3',
            };
            localState[protocol.STORAGE_KEYS.PREFERENCES] = { lang: 'en' };
            syncState[protocol.STORAGE_KEYS.PREFERENCES] = {
              lang: 'zh', sortOrder: 'alpha-asc',
            };
            console.log(JSON.stringify({
              llm: await store.loadLlmSettings(),
              draft: await store.loadUiDraft(),
              preferences: await store.loadPreferences(),
            }));
            """
        )
        self.assertEqual(result["llm"], {
            "apiBaseUrl": "https://api.openai.com/v1",
            "apiStyle": "auto",
            "model": "custom-model",
            "requestTimeout": "180",
        })
        self.assertEqual(result["draft"], {
            "activeTab": "strategy",
            "apiBaseUrl": "draft://raw-value",
            "apiStyle": "raw-style",
            "model": "",
            "requestTimeout": "0",
            "focusPath": "",
            "maxActions": "40",
            "maxRetries": "3",
            "userInstruction": "",
        })
        self.assertEqual(result["preferences"], {
            "protectRootLooseBookmarks": "yes",
            "sortOrder": "alpha-asc",
            "planningStyle": "balanced",
            "lang": "zh",
        })

    def test_host_permission_granted_skips_request_and_uses_origin_pattern(self) -> None:
        result = self._node_eval(
            """
            containsGranted = true;
            requestGranted = false;
            const normalized = store.normalizeHttpsBaseUrl(
              'https://api.example.com:8443/v1/chat/completions/?query=drop#drop',
            );
            const origin = store.extractOrigin(normalized);
            const ensured = await store.ensureHostPermission(normalized);
            const directCheck = await store.checkHostPermission(origin);
            const emptyCheck = await store.checkHostPermission('');
            console.log(JSON.stringify({
              normalized, origin, ensured, directCheck, emptyCheck, permissionCalls,
            }));
            """
        )
        self.assertEqual(
            result["normalized"],
            "https://api.example.com:8443/v1/chat/completions",
        )
        self.assertEqual(result["origin"], "https://api.example.com:8443/*")
        self.assertTrue(result["ensured"])
        self.assertTrue(result["directCheck"])
        self.assertFalse(result["emptyCheck"])
        self.assertEqual(
            result["permissionCalls"],
            [
                ["contains", {"origins": ["https://api.example.com:8443/*"]}],
                ["contains", {"origins": ["https://api.example.com:8443/*"]}],
            ],
        )

    def test_permission_request_denial_and_sync_storage_fallbacks(self) -> None:
        result = self._node_eval(
            """
            containsGranted = false;
            requestGranted = true;
            const grantedAfterRequest = await store.ensureHostPermission('https://new.example/v1');
            requestGranted = false;
            const deniedAfterRequest = await store.ensureHostPermission('https://denied.example/v1');

            localState[protocol.STORAGE_KEYS.PREFERENCES] = {
              protectRootLooseBookmarks: 'no', sortOrder: 'alpha-asc',
              planningStyle: 'aggressive', lang: 'zh',
            };
            syncGetError = 'chrome.storage.sync is unavailable';
            const loadedFromLocal = await store.loadPreferences();
            syncGetError = '';
            syncSetError = 'sync quota exceeded';
            const savedToLocal = await store.savePreferences({
              protectRootLooseBookmarks: 'yes', sortOrder: 'alpha-desc',
              planningStyle: 'conservative', lang: 'en',
            });
            syncSetError = '';
            syncGetError = 'quota exceeded';
            let nonSyncError = '';
            try { await store.loadPreferences(); }
            catch (error) { nonSyncError = error.message; }

            const noPermissionsStore = BookmarkAdvisor.Popup.SettingsStore.create({
              chrome: { runtime: { lastError: null }, storage: chrome.storage },
              protocol,
              aiEndpoint,
            });
            console.log(JSON.stringify({
              grantedAfterRequest,
              deniedAfterRequest,
              loadedFromLocal,
              savedToLocal,
              localAfterSave: localState[protocol.STORAGE_KEYS.PREFERENCES],
              nonSyncError,
              emptyEnsure: await noPermissionsStore.ensureHostPermission(''),
              missingPermissionsCheck: await noPermissionsStore.checkHostPermission('https://x.example/*'),
              permissionCalls,
            }));
            """
        )
        self.assertTrue(result["grantedAfterRequest"])
        self.assertFalse(result["deniedAfterRequest"])
        self.assertEqual(
            result["permissionCalls"],
            [
                ["contains", {"origins": ["https://new.example/*"]}],
                ["request", {"origins": ["https://new.example/*"]}],
                ["contains", {"origins": ["https://denied.example/*"]}],
                ["request", {"origins": ["https://denied.example/*"]}],
            ],
        )
        self.assertEqual(result["loadedFromLocal"]["lang"], "zh")
        self.assertEqual(result["loadedFromLocal"]["planningStyle"], "aggressive")
        self.assertEqual(result["savedToLocal"], result["localAfterSave"])
        self.assertEqual(result["localAfterSave"]["sortOrder"], "alpha-desc")
        self.assertEqual(result["nonSyncError"], "quota exceeded")
        self.assertFalse(result["emptyEnsure"])
        self.assertFalse(result["missingPermissionsCheck"])


if __name__ == "__main__":
    unittest.main()
