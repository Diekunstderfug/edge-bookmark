"""Extension service worker state persistence tests."""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import cast


_REPO_ROOT = Path(__file__).resolve().parent.parent
_SERVICE_WORKER = _REPO_ROOT / "extension" / "service_worker.js"


@unittest.skipUnless(shutil.which("node"), "node is required for extension JS service worker tests")
class ExtensionServiceWorkerStateTest(unittest.TestCase):
    def _node_script(self, body: str) -> object:
        completed = subprocess.run(
            ["node", "-e", body],
            check=True,
            capture_output=True,
            text=True,
            cwd=_REPO_ROOT,
        )
        return cast(object, json.loads(completed.stdout))

    def test_generate_ai_plan_persists_result_outside_popup(self):
        script = f"""
        const path = require('path');
        const repoRoot = {json.dumps(str(_REPO_ROOT))};
        const serviceWorkerPath = {json.dumps(str(_SERVICE_WORKER))};
        const storage = {{}};
        let listener = null;
        global.importScripts = function (...files) {{
          for (const file of files) {{
            require(path.join(repoRoot, 'extension', file));
          }}
        }};
        global.chrome = {{
          runtime: {{
            id: 'test-extension',
            lastError: null,
            getURL: (file) => `chrome-extension://test/${{file}}`,
            onMessage: {{ addListener: (callback) => {{ listener = callback; }} }}
          }},
          storage: {{
            local: {{
              set: (value, callback) => {{ Object.assign(storage, value); if (callback) callback(); }},
              get: (key, callback) => {{ callback({{ [key]: storage[key] }}); }},
              remove: (key, callback) => {{ delete storage[key]; if (callback) callback(); }}
            }}
          }},
          bookmarks: {{
            getTree: (callback) => callback([{{
              id: '0',
              title: '',
              children: [{{
                id: '1',
                title: '收藏夹栏',
                children: [{{
                  id: '2',
                  title: 'Loose',
                  children: [{{ id: '10', title: 'Example', url: 'https://example.com' }}]
                }}]
              }}]
            }}])
          }}
        }};
        global.fetch = async function (url, options) {{
          if (String(url).startsWith('chrome-extension://')) {{
            return {{ ok: false, json: async () => ({{}}), text: async () => '' }};
          }}
          const payload = {{
            summary: {{ overview: 'generated while popup is closed' }},
            activations: [{{
              op: 'move_bookmark',
              node_kind: 'bookmark',
              node_id: '10',
              destination_path: '/收藏夹栏/AI',
              create_path: '',
              new_title: '',
              duplicate_of_id: '',
              confidence: 0.91,
              reason: 'belongs with AI tools'
            }}]
          }};
          return {{
            ok: true,
            text: async () => JSON.stringify({{ choices: [{{ text: JSON.stringify(payload) }}] }})
          }};
        }};
        require(serviceWorkerPath);
        new Promise((resolve, reject) => {{
          listener({{
            type: 'generate-ai-plan',
            options: {{
              apiKey: 'test-key',
              apiBaseUrl: 'https://api.example.com/v1/completions',
              apiStyle: 'completions',
              model: 'test-model'
            }}
          }}, null, (response) => {{
            if (response && response.error) reject(new Error(response.error));
            else resolve(response);
          }});
        }}).then((response) => {{
          const saved = storage.bookmarkAdvisorLastPlan;
          console.log(JSON.stringify({{
            responseActionType: response.reviewed_plan.actions[0].action_type,
            savedActionType: saved.plan.actions[0].action_type,
            savedAtPresent: typeof saved.saved_at === 'string',
            progressMessage: storage.bookmarkAdvisorProgress.message
          }}));
        }}).catch((error) => {{
          console.error(error && error.stack ? error.stack : String(error));
          process.exit(1);
        }});
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["responseActionType"], "move_bookmark")
        self.assertEqual(result["savedActionType"], "move_bookmark")
        self.assertEqual(result["savedAtPresent"], True)
        self.assertEqual(result["progressMessage"], "AI plan generated and saved for popup restore.")

    def test_background_job_returns_immediately_then_persists_result(self):
        script = f"""
        const path = require('path');
        const repoRoot = {json.dumps(str(_REPO_ROOT))};
        const serviceWorkerPath = {json.dumps(str(_SERVICE_WORKER))};
        const storage = {{}};
        let listener = null;
        global.importScripts = function (...files) {{
          for (const file of files) {{
            require(path.join(repoRoot, 'extension', file));
          }}
        }};
        global.chrome = {{
          runtime: {{ id: 'test-extension', lastError: null, getURL: (file) => `chrome-extension://test/${{file}}`, onMessage: {{ addListener: (callback) => {{ listener = callback; }} }} }},
          storage: {{ local: {{ set: (value, callback) => {{ Object.assign(storage, value); if (callback) callback(); }}, get: (key, callback) => {{ callback({{ [key]: storage[key] }}); }}, remove: (key, callback) => {{ delete storage[key]; if (callback) callback(); }} }} }},
          bookmarks: {{ getTree: (callback) => callback([{{ id: '0', title: '', children: [{{ id: '1', title: '收藏夹栏', children: [{{ id: '2', title: 'Loose', children: [{{ id: '10', title: 'Example', url: 'https://example.com' }}] }}] }}] }}]) }}
        }};
        global.fetch = async function (url) {{
          if (String(url).startsWith('chrome-extension://')) return {{ ok: false, json: async () => ({{}}), text: async () => '' }};
          await new Promise((resolve) => setTimeout(resolve, 20));
          const payload = {{ summary: {{ overview: 'background job' }}, activations: [{{ op: 'move_bookmark', node_kind: 'bookmark', node_id: '10', destination_path: '/收藏夹栏/AI', create_path: '', new_title: '', duplicate_of_id: '', confidence: 0.91, reason: 'belongs with AI tools' }}] }};
          return {{ ok: true, text: async () => JSON.stringify({{ choices: [{{ text: JSON.stringify(payload) }}] }}) }};
        }};
        require(serviceWorkerPath);
        new Promise((resolve, reject) => {{
          listener({{ type: 'start-background-job', job_type: 'generate-ai-plan', payload: {{ options: {{ apiKey: 'test-key', apiBaseUrl: 'https://api.example.com/v1/completions', apiStyle: 'completions', model: 'test-model' }} }} }}, null, (response) => response && response.error ? reject(new Error(response.error)) : resolve(response));
        }}).then((response) => {{
          const startedStatus = response.job.status;
          return new Promise((resolve) => setTimeout(() => resolve(startedStatus), 80));
        }}).then((startedStatus) => {{
          console.log(JSON.stringify({{
            startedStatus,
            finalStatus: storage.bookmarkAdvisorActiveJob.status,
            resultActionType: storage.bookmarkAdvisorActiveJob.result.reviewed_plan.actions[0].action_type,
            savedActionType: storage.bookmarkAdvisorLastPlan.plan.actions[0].action_type
          }}));
        }}).catch((error) => {{
          console.error(error && error.stack ? error.stack : String(error));
          process.exit(1);
        }});
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["startedStatus"], "running")
        self.assertEqual(result["finalStatus"], "succeeded")
        self.assertEqual(result["resultActionType"], "move_bookmark")
        self.assertEqual(result["savedActionType"], "move_bookmark")

    def test_background_job_ack_uses_async_storage_lock_before_executor(self):
        script = f"""
        const path = require('path');
        const repoRoot = {json.dumps(str(_REPO_ROOT))};
        const serviceWorkerPath = {json.dumps(str(_SERVICE_WORKER))};
        let listener = null;
        let storageSetCalled = false;
        global.importScripts = function (...files) {{
          for (const file of files) {{ require(path.join(repoRoot, 'extension', file)); }}
        }};
        global.chrome = {{
          runtime: {{ id: 'test-extension', lastError: null, getURL: (file) => `chrome-extension://test/${{file}}`, onMessage: {{ addListener: (callback) => {{ listener = callback; }} }} }},
          storage: {{ local: {{
            set: (_value, _callback) => {{ storageSetCalled = true; }},
            get: (_key, callback) => callback({{}}),
            remove: (_key, callback) => {{ if (callback) callback(); }}
          }} }},
          bookmarks: {{ getTree: () => {{ throw new Error('should not reach executor before ack'); }} }}
        }};
        global.fetch = async () => {{ throw new Error('should not fetch before ack'); }};
        require(serviceWorkerPath);
        let response = null;
        const returnValue = listener({{ type: 'start-background-job', job_type: 'generate-ai-plan', payload: {{ options: {{}} }} }}, null, (value) => {{ response = value; }});
        setTimeout(() => {{
          console.log(JSON.stringify({{
            returnedAsync: returnValue === true,
            hasResponse: !!response,
            jobStatus: response && response.job && response.job.status,
            storageSetCalled
          }}));
        }}, 0);
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["returnedAsync"], True)
        self.assertEqual(result["hasResponse"], True)
        self.assertEqual(result["jobStatus"], "running")
        self.assertEqual(result["storageSetCalled"], True)

    def test_background_job_rejects_existing_running_job(self):
        script = f"""
        const path = require('path');
        const repoRoot = {json.dumps(str(_REPO_ROOT))};
        const serviceWorkerPath = {json.dumps(str(_SERVICE_WORKER))};
        const storage = {{ bookmarkAdvisorActiveJob: {{ id: 'job-existing', type: 'generate-ai-plan', status: 'running', updated_at: new Date().toISOString() }} }};
        let listener = null;
        global.importScripts = function (...files) {{
          for (const file of files) {{ require(path.join(repoRoot, 'extension', file)); }}
        }};
        global.chrome = {{
          runtime: {{ id: 'test-extension', lastError: null, getURL: (file) => `chrome-extension://test/${{file}}`, onMessage: {{ addListener: (callback) => {{ listener = callback; }} }} }},
          storage: {{ local: {{
            set: (value, callback) => {{ Object.assign(storage, value); if (callback) callback(); }},
            get: (key, callback) => callback({{ [key]: storage[key] }}),
            remove: (_key, callback) => {{ if (callback) callback(); }}
          }} }},
          bookmarks: {{ getTree: () => {{ throw new Error('should not execute while locked'); }} }}
        }};
        global.fetch = async () => {{ throw new Error('should not fetch while locked'); }};
        require(serviceWorkerPath);
        listener({{ type: 'start-background-job', job_type: 'apply-reviewed-plan', payload: {{ plan: {{ actions: [] }} }} }}, null, (response) => {{
          console.log(JSON.stringify({{ error: response.error }}));
        }});
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertIn("already running", str(result["error"]))


if __name__ == "__main__":
    _ = unittest.main()
