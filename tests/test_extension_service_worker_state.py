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
            timeout=15,
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
        async function waitForFinalJob() {{
          const deadline = Date.now() + 1000;
          while (Date.now() < deadline) {{
            if (storage.bookmarkAdvisorActiveJob && storage.bookmarkAdvisorActiveJob.status !== 'running') {{
              return storage.bookmarkAdvisorActiveJob;
            }}
            await new Promise((resolve) => setTimeout(resolve, 5));
          }}
          throw new Error('job did not reach a final state');
        }}
        require(serviceWorkerPath);
        new Promise((resolve, reject) => {{
          listener({{ type: 'start-background-job', job_type: 'generate-ai-plan', payload: {{ options: {{ apiKey: 'test-key', apiBaseUrl: 'https://api.example.com/v1/completions', apiStyle: 'completions', model: 'test-model' }} }} }}, null, (response) => response && response.error ? reject(new Error(response.error)) : resolve(response));
        }}).then((response) => {{
          const startedStatus = response.job.status;
          return waitForFinalJob().then((finalJob) => [startedStatus, finalJob]);
        }}).then(([startedStatus, finalJob]) => {{
          console.log(JSON.stringify({{
            startedStatus,
            finalStatus: finalJob.status,
            resultActionType: finalJob.result.reviewed_plan.actions[0].action_type,
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

    def test_concurrent_background_jobs_only_start_one_executor(self):
        script = f"""
        const path = require('path');
        const repoRoot = {json.dumps(str(_REPO_ROOT))};
        const serviceWorkerPath = {json.dumps(str(_SERVICE_WORKER))};
        const storage = {{}};
        let listener = null;
        let getTreeCalls = 0;
        global.importScripts = function (...files) {{
          for (const file of files) {{ require(path.join(repoRoot, 'extension', file)); }}
        }};
        global.chrome = {{
          runtime: {{ id: 'test-extension', lastError: null, getURL: (file) => `chrome-extension://test/${{file}}`, onMessage: {{ addListener: (callback) => {{ listener = callback; }} }} }},
          storage: {{ local: {{
            set: (value, callback) => {{ Object.assign(storage, value); if (callback) callback(); }},
            get: (key, callback) => setTimeout(() => callback({{ [key]: storage[key] }}), 10),
            remove: (_key, callback) => {{ if (callback) callback(); }}
          }} }},
          bookmarks: {{ getTree: (callback) => {{ getTreeCalls += 1; callback([{{ id: '0', title: '', children: [] }}]); }} }}
        }};
        global.fetch = async () => {{
          return {{ ok: true, text: async () => JSON.stringify({{ choices: [{{ text: JSON.stringify({{ summary: {{ overview: 'ok' }}, activations: [] }}) }}] }}) }};
        }};
        require(serviceWorkerPath);
        function start() {{
          return new Promise((resolve) => {{
            listener({{ type: 'start-background-job', job_type: 'generate-ai-plan', payload: {{ options: {{ apiKey: 'test-key', apiBaseUrl: 'https://api.example.com/v1/completions', apiStyle: 'completions', model: 'test-model' }} }} }}, null, resolve);
          }});
        }}
        Promise.all([start(), start()]).then((responses) => {{
          setTimeout(() => {{
            console.log(JSON.stringify({{
              started: responses.filter((item) => item && item.job).length,
              rejected: responses.filter((item) => item && item.error).length,
              getTreeCalls
            }}));
          }}, 50);
        }}).catch((error) => {{
          console.error(error && error.stack ? error.stack : String(error));
          process.exit(1);
        }});
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["started"], 1)
        self.assertEqual(result["rejected"], 1)

    def test_late_ai_progress_does_not_overwrite_finished_background_job(self):
        script = f"""
        const path = require('path');
        const repoRoot = {json.dumps(str(_REPO_ROOT))};
        const serviceWorkerPath = {json.dumps(str(_SERVICE_WORKER))};
        const storage = {{}};
        let listener = null;
        global.importScripts = function (...files) {{
          for (const file of files) {{ require(path.join(repoRoot, 'extension', file)); }}
        }};
        global.chrome = {{
          runtime: {{ id: 'test-extension', lastError: null, getURL: (file) => `chrome-extension://test/${{file}}`, onMessage: {{ addListener: (callback) => {{ listener = callback; }} }} }},
          storage: {{ local: {{
            set: (value, callback) => {{
              const job = value.bookmarkAdvisorActiveJob;
              const delay = job && job.status === 'running' && String(job.progress || '').includes('Parsing and linting') ? 50 : 0;
              setTimeout(() => {{ Object.assign(storage, value); if (callback) callback(); }}, delay);
            }},
            get: (key, callback) => callback({{ [key]: storage[key] }}),
            remove: (key, callback) => {{ delete storage[key]; if (callback) callback(); }}
          }} }},
          bookmarks: {{ getTree: (callback) => callback([{{ id: '0', title: '', children: [{{ id: '1', title: '收藏夹栏', children: [] }}] }}]) }}
        }};
        global.fetch = async () => {{
          return {{ ok: true, text: async () => JSON.stringify({{ choices: [{{ text: JSON.stringify({{ summary: {{ overview: 'ok' }}, activations: [] }}) }}] }}) }};
        }};
        require(serviceWorkerPath);
        listener({{ type: 'start-background-job', job_type: 'generate-ai-plan', payload: {{ options: {{ apiKey: 'test-key', apiBaseUrl: 'https://api.example.com/v1/completions', apiStyle: 'completions', model: 'test-model' }} }} }}, null, (response) => {{
          setTimeout(() => {{
            console.log(JSON.stringify({{
              started: !!response.job,
              finalStatus: storage.bookmarkAdvisorActiveJob.status,
              finalProgress: storage.bookmarkAdvisorActiveJob.progress
            }}));
          }}, 100);
        }});
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["started"], True)
        self.assertEqual(result["finalStatus"], "succeeded")

    def test_direct_mutating_message_respects_active_background_job(self):
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
        require(serviceWorkerPath);
        listener({{ type: 'apply-reviewed-plan', plan: {{ actions: [] }} }}, null, (response) => {{
          console.log(JSON.stringify({{ error: response.failures[0].error }}));
        }});
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertIn("already running", str(result["error"]))

    def test_proposed_actions_are_not_executed(self):
        script = f"""
        const path = require('path');
        const repoRoot = {json.dumps(str(_REPO_ROOT))};
        const serviceWorkerPath = {json.dumps(str(_SERVICE_WORKER))};
        const storage = {{}};
        let listener = null;
        let moveCalls = 0;
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
          bookmarks: {{
            move: () => {{ moveCalls += 1; throw new Error('proposed should not move'); }},
            getTree: (callback) => callback([])
          }}
        }};
        require(serviceWorkerPath);
        listener({{ type: 'apply-reviewed-plan', plan: {{ actions: [{{
          action_id: 'a-1',
          action_type: 'move_bookmark',
          status: 'proposed',
          reason: 'draft',
          confidence: 0.3,
          bookmark_locator: {{ id: '10', title: 'Example', url: 'https://example.com', normalized_url: 'https://example.com', folder_path: '/收藏夹栏' }},
          to_path: '/收藏夹栏/AI'
        }}] }} }}, null, (response) => {{
          console.log(JSON.stringify({{ succeeded: response.succeeded.length, failures: response.failures.length, moveCalls }}));
        }});
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["succeeded"], 0)
        self.assertEqual(result["failures"], 0)
        self.assertEqual(result["moveCalls"], 0)

    def test_locator_id_metadata_mismatch_fails_closed(self):
        script = f"""
        const path = require('path');
        const repoRoot = {json.dumps(str(_REPO_ROOT))};
        const serviceWorkerPath = {json.dumps(str(_SERVICE_WORKER))};
        const storage = {{}};
        let listener = null;
        let removeCalls = 0;
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
          bookmarks: {{
            get: (id, callback) => callback([{{ id, title: 'Different', url: 'https://other.example/', parentId: '1' }}]),
            remove: () => {{ removeCalls += 1; }},
            getTree: (callback) => callback([{{ id: '0', title: '', children: [] }}])
          }}
        }};
        require(serviceWorkerPath);
        listener({{ type: 'apply-reviewed-plan', plan: {{ actions: [{{
          action_id: 'a-1',
          action_type: 'remove_duplicate',
          status: 'approved',
          reason: 'dedupe',
          confidence: 0.9,
          bookmark_locator: {{ id: '10', title: 'Example', url: 'https://example.com', normalized_url: 'https://example.com', folder_path: '/收藏夹栏' }}
        }}] }} }}, null, (response) => {{
          console.log(JSON.stringify({{ failures: response.failures.length, error: response.failures[0].error, removeCalls }}));
        }});
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["failures"], 1)
        self.assertEqual(result["removeCalls"], 0)
        self.assertIn("did not match", str(result["error"]))

    def test_stale_bookmark_id_can_fall_back_to_unique_locator_match(self):
        script = f"""
        const path = require('path');
        const repoRoot = {json.dumps(str(_REPO_ROOT))};
        const serviceWorkerPath = {json.dumps(str(_SERVICE_WORKER))};
        const storage = {{}};
        let listener = null;
        let removeCalls = [];
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
          bookmarks: {{
            get: (id, callback) => callback(id === '1' ? [{{ id: '1', title: '收藏夹栏', children: [] }}] : []),
            search: (_query, callback) => callback([{{ id: '99', title: 'Example', url: 'https://example.com', parentId: '1' }}]),
            getTree: (callback) => callback([{{ id: '0', title: '', children: [{{ id: '1', title: '收藏夹栏', children: [{{ id: '99', title: 'Example', url: 'https://example.com' }}] }}] }}]),
            remove: (id, callback) => {{ removeCalls.push(id); if (callback) callback(); }}
          }}
        }};
        require(serviceWorkerPath);
        listener({{ type: 'apply-reviewed-plan', plan: {{ actions: [{{
          action_id: 'a-1',
          action_type: 'remove_duplicate',
          status: 'approved',
          reason: 'dedupe',
          confidence: 0.9,
          bookmark_locator: {{ id: '10', title: 'Example', url: 'https://example.com', normalized_url: 'https://example.com', folder_path: '/收藏夹栏' }}
        }}] }} }}, null, (response) => {{
          console.log(JSON.stringify({{ succeeded: response.succeeded.length, failures: response.failures.length, removeCalls }}));
        }});
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["failures"], 0)
        self.assertEqual(result["removeCalls"], ["99"])


if __name__ == "__main__":
    _ = unittest.main()
