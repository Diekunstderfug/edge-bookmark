"""Independent tests for popup API-key obfuscation and draft storage."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"


class ExtensionPopupSecretsTest(unittest.TestCase):
    def _node_eval(self, body: str) -> Any:
        script = f"""
          require({json.dumps(str(EXTENSION / 'popup' / 'secrets.js'))});

          function makeChrome(options = {{}}) {{
            const local = options.local || Object.create(null);
            const session = options.session || Object.create(null);
            const failures = options.failures || Object.create(null);
            const chrome = {{
              runtime: {{ id: options.runtimeId || 'extension-a', lastError: null }},
              storage: {{}},
            }};

            function finish(kind, operation, callback, value) {{
              const message = failures[`${{kind}}.${{operation}}`] || '';
              chrome.runtime.lastError = message ? {{ message }} : null;
              callback(value);
              chrome.runtime.lastError = null;
            }}

            function createArea(kind, values) {{
              return {{
                get(key, callback) {{
                  finish(kind, 'get', callback, {{ [key]: values[key] }});
                }},
                set(value, callback) {{
                  if (!failures[`${{kind}}.set`]) Object.assign(values, value);
                  finish(kind, 'set', callback || (() => {{}}));
                }},
                remove(key, callback) {{
                  if (!failures[`${{kind}}.remove`]) {{
                    if (Array.isArray(key)) key.forEach((item) => delete values[item]);
                    else delete values[key];
                  }}
                  finish(kind, 'remove', callback || (() => {{}}));
                }},
              }};
            }}

            chrome.storage.local = createArea('local', local);
            if (options.includeSession !== false) {{
              chrome.storage.session = createArea('session', session);
            }}
            return {{ chrome, local, session, failures }};
          }}

          (async () => {{
            {body}
          }})().catch((error) => {{
            console.error(error && error.stack ? error.stack : String(error));
            process.exit(1);
          }});
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

    def test_active_key_and_low_level_secret_roundtrip_preserve_v2_payload_schema(self) -> None:
        result = self._node_eval(
            """
            const harness = makeChrome();
            const secrets = BookmarkAdvisor.Popup.Secrets.create({
              chrome: harness.chrome,
              crypto: globalThis.crypto,
            });
            await secrets.saveActiveKey('sk-秘密-value');
            const active = await secrets.loadActiveKey();
            await secrets.saveSecret('custom-secret', 'custom-value');
            const custom = await secrets.loadSecret('custom-secret');
            const record = harness.local.bookmarkAdvisorOpenAIKey;
            const bytes = Uint8Array.from([0, 1, 2, 127, 128, 255]);
            const encoded = secrets.bytesToBase64(bytes);
            const decoded = [...secrets.base64ToBytes(encoded)];
            const derivedKey = await secrets.deriveAutomaticStorageKey(
              secrets.base64ToBytes(record.salt),
            );
            console.log(JSON.stringify({
              active, custom, record, encoded, decoded,
              derivedKeyType: derivedKey.type,
              derivedKeyExtractable: derivedKey.extractable,
              derivedKeyUsages: [...derivedKey.usages].sort(),
            }));
            """
        )
        self.assertEqual(result["active"], "sk-秘密-value")
        self.assertEqual(result["custom"], "custom-value")
        record = result["record"]
        self.assertEqual(record["version"], 2)
        self.assertEqual(record["kdf"], "SHA-256(runtime-id)")
        self.assertEqual(record["cipher"], "AES-GCM")
        self.assertRegex(record["created_at"], r"^\d{4}-\d{2}-\d{2}T.*Z$")
        self.assertNotIn("sk-秘密-value", json.dumps(record, ensure_ascii=False))
        self.assertEqual(len(result["decoded"]), 6)
        self.assertEqual(result["decoded"], [0, 1, 2, 127, 128, 255])
        self.assertEqual(result["derivedKeyType"], "secret")
        self.assertFalse(result["derivedKeyExtractable"])
        self.assertEqual(result["derivedKeyUsages"], ["decrypt", "encrypt"])

    def test_different_runtime_id_or_purpose_cannot_decrypt_existing_record(self) -> None:
        result = self._node_eval(
            """
            const harness = makeChrome({ runtimeId: 'extension-a' });
            const original = BookmarkAdvisor.Popup.Secrets.create({
              chrome: harness.chrome, crypto: globalThis.crypto,
            });
            await original.saveActiveKey('runtime-bound-value');

            async function capture(client) {
              try { return { value: await client.loadActiveKey(), error: null }; }
              catch (error) { return { value: null, error: { name: error.name, message: error.message } }; }
            }
            const otherRuntime = BookmarkAdvisor.Popup.Secrets.create({
              chrome: harness.chrome, crypto: globalThis.crypto, runtimeId: 'extension-b',
            });
            const otherPurpose = BookmarkAdvisor.Popup.Secrets.create({
              chrome: harness.chrome, crypto: globalThis.crypto, purpose: 'different-purpose',
            });
            console.log(JSON.stringify({
              original: await original.loadActiveKey(),
              otherRuntime: await capture(otherRuntime),
              otherPurpose: await capture(otherPurpose),
            }));
            """
        )
        self.assertEqual(result["original"], "runtime-bound-value")
        self.assertIsNone(result["otherRuntime"]["value"])
        self.assertEqual(result["otherRuntime"]["error"]["name"], "OperationError")
        self.assertIsNone(result["otherPurpose"]["value"])
        self.assertEqual(result["otherPurpose"]["error"]["name"], "OperationError")

    def test_missing_and_old_payloads_keep_migration_error_messages(self) -> None:
        result = self._node_eval(
            """
            const harness = makeChrome();
            const secrets = BookmarkAdvisor.Popup.Secrets.create({
              chrome: harness.chrome, crypto: globalThis.crypto,
            });
            async function capture() {
              try { return await secrets.loadActiveKey(); }
              catch (error) { return error.message; }
            }
            const missing = await capture();
            harness.local.bookmarkAdvisorOpenAIKey = {
              version: 1,
              cipher: 'AES-GCM',
              salt: 'legacy',
              iv: 'legacy',
              ciphertext: 'legacy',
            };
            const old = await capture();
            harness.local.bookmarkAdvisorOpenAIKey.version = '2';
            const stringVersion = await capture();
            console.log(JSON.stringify({ missing, old, stringVersion }));
            """
        )
        self.assertEqual(
            result["missing"],
            "No usable obfuscated API key found. Paste one in Settings.",
        )
        self.assertEqual(
            result["old"],
            "Older passphrase-protected key found. Paste the key and save again to migrate.",
        )
        self.assertEqual(result["stringVersion"], result["old"])

    def test_draft_prefers_session_migrates_local_fallback_and_clears_both_areas(self) -> None:
        result = self._node_eval(
            """
            const harness = makeChrome();
            const secrets = BookmarkAdvisor.Popup.Secrets.create({
              chrome: harness.chrome, crypto: globalThis.crypto,
            });
            const draftKey = 'bookmarkAdvisorOpenAIKeyDraft';

            await secrets.saveSecret(draftKey, 'legacy-local-draft', harness.chrome.storage.local);
            const migrated = await secrets.loadDraft();
            const afterMigration = {
              local: !!harness.local[draftKey],
              session: !!harness.session[draftKey],
            };

            await secrets.saveSecret(draftKey, 'stale-local-draft', harness.chrome.storage.local);
            await secrets.saveDraft('fresh-session-draft');
            const loaded = await secrets.loadDraft();
            const afterSave = {
              local: !!harness.local[draftKey],
              session: !!harness.session[draftKey],
            };
            const selectedSession = secrets.draftStorageArea() === harness.chrome.storage.session;
            await secrets.clearDraft();
            console.log(JSON.stringify({
              migrated, afterMigration, loaded, afterSave, selectedSession,
              afterClear: {
                local: !!harness.local[draftKey],
                session: !!harness.session[draftKey],
              },
            }));
            """
        )
        self.assertEqual(result["migrated"], "legacy-local-draft")
        self.assertEqual(result["afterMigration"], {"local": False, "session": True})
        self.assertEqual(result["loaded"], "fresh-session-draft")
        self.assertEqual(result["afterSave"], {"local": False, "session": True})
        self.assertTrue(result["selectedSession"])
        self.assertEqual(result["afterClear"], {"local": False, "session": False})

    def test_draft_falls_back_to_local_when_session_storage_is_unavailable(self) -> None:
        result = self._node_eval(
            """
            const harness = makeChrome({ includeSession: false });
            const secrets = BookmarkAdvisor.Popup.Secrets.create({
              chrome: harness.chrome, crypto: globalThis.crypto,
            });
            await secrets.saveDraft('local-only-draft');
            const loaded = await secrets.loadDraft();
            const selectedLocal = secrets.draftStorageArea() === harness.chrome.storage.local;
            console.log(JSON.stringify({
              loaded, selectedLocal,
              hasLocal: !!harness.local.bookmarkAdvisorOpenAIKeyDraft,
              hasSessionArea: !!harness.chrome.storage.session,
            }));
            """
        )
        self.assertEqual(result["loaded"], "local-only-draft")
        self.assertTrue(result["selectedLocal"])
        self.assertTrue(result["hasLocal"])
        self.assertFalse(result["hasSessionArea"])

    def test_storage_area_adapter_propagates_last_error_while_clear_is_best_effort(self) -> None:
        result = self._node_eval(
            """
            const harness = makeChrome();
            const secrets = BookmarkAdvisor.Popup.Secrets.create({
              chrome: harness.chrome, crypto: globalThis.crypto,
            });
            async function capture(callback) {
              try { await callback(); return ''; }
              catch (error) { return error.message; }
            }

            harness.failures['local.set'] = 'storage write failed';
            const writeError = await capture(() => secrets.saveActiveKey('value'));
            delete harness.failures['local.set'];

            harness.failures['local.get'] = 'storage read failed';
            const readError = await capture(() => secrets.loadActiveKey());
            delete harness.failures['local.get'];

            harness.failures['local.remove'] = 'storage remove failed';
            const removeError = await capture(() => secrets.removeFromArea(
              harness.chrome.storage.local, 'anything',
            ));
            harness.failures['session.remove'] = 'session remove failed';
            const clearError = await capture(() => secrets.clearDraft());
            console.log(JSON.stringify({ writeError, readError, removeError, clearError }));
            """
        )
        self.assertEqual(result["writeError"], "storage write failed")
        self.assertEqual(result["readError"], "storage read failed")
        self.assertEqual(result["removeError"], "storage remove failed")
        self.assertEqual(result["clearError"], "")


if __name__ == "__main__":
    unittest.main()
