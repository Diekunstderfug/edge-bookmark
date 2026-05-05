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
              node_id: '10',
              target: '/收藏夹栏/AI',
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
          const payload = {{ summary: {{ overview: 'background job' }}, activations: [{{ op: 'move_bookmark', node_id: '10', target: '/收藏夹栏/AI', duplicate_of_id: '', confidence: 0.91, reason: 'belongs with AI tools' }}] }};
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

    def test_cancel_active_job_aborts_inflight_ai_job_and_persists_cancelled_state(self):
        script = f"""
        const path = require('path');
        const repoRoot = {json.dumps(str(_REPO_ROOT))};
        const serviceWorkerPath = {json.dumps(str(_SERVICE_WORKER))};
        const storage = {{}};
        let listener = null;
        let planningSignalAborted = false;
        let planningFetchStarted = false;
        global.importScripts = function (...files) {{
          for (const file of files) {{ require(path.join(repoRoot, 'extension', file)); }}
        }};
        global.chrome = {{
          runtime: {{ id: 'test-extension', lastError: null, getURL: (file) => `chrome-extension://test/${{file}}`, onMessage: {{ addListener: (callback) => {{ listener = callback; }} }} }},
          storage: {{ local: {{
            set: (value, callback) => {{ Object.assign(storage, value); if (callback) callback(); }},
            get: (key, callback) => callback({{ [key]: storage[key] }}),
            remove: (key, callback) => {{ delete storage[key]; if (callback) callback(); }}
          }} }},
          bookmarks: {{ getTree: (callback) => callback([{{ id: '0', title: '', children: [{{ id: '1', title: '收藏夹栏', children: [{{ id: '2', title: 'Loose', children: [{{ id: '10', title: 'Example', url: 'https://example.com' }}] }}] }}] }}]) }}
        }};
        global.fetch = async function (url, options) {{
          if (String(url).includes('fast_rules.json')) {{
            return {{
              ok: true,
              json: async () => ({{
                defaults: {{ protect_root_loose_bookmarks: true, allow_new_folders_in_advise: true }},
                protected_paths: ['/收藏夹栏', '/其他收藏夹', '/移动收藏夹', '/工作区'],
                category_hints: {{}},
                folder_relocations: [],
                bookmark_relocations: []
              }})
            }};
          }}
          if (!options.signal) {{
            throw new Error('missing signal');
          }}
          planningFetchStarted = true;
          options.signal.addEventListener('abort', () => {{ planningSignalAborted = true; }}, {{ once: true }});
          return await new Promise((resolve, reject) => {{
            if (options.signal.aborted) {{
              const error = new Error('aborted by test');
              error.name = 'AbortError';
              reject(error);
              return;
            }}
            const timeoutId = setTimeout(() => reject(new Error('did not abort')), 250);
            options.signal.addEventListener('abort', () => {{
              clearTimeout(timeoutId);
              const error = new Error('aborted by test');
              error.name = 'AbortError';
              reject(error);
            }}, {{ once: true }});
          }});
        }};
        function waitFor(predicate, deadlineMs = 1000) {{
          const deadline = Date.now() + deadlineMs;
          return new Promise((resolve, reject) => {{
            function tick() {{
              if (predicate()) {{
                resolve();
                return;
              }}
              if (Date.now() > deadline) {{
                reject(new Error('timed out waiting for condition'));
                return;
              }}
              setTimeout(tick, 5);
            }}
            tick();
          }});
        }}
        require(serviceWorkerPath);
        new Promise((resolve, reject) => {{
          listener({{ type: 'start-background-job', job_type: 'generate-ai-plan', payload: {{ options: {{ apiKey: 'test-key', apiBaseUrl: 'https://api.example.com/v1/completions', apiStyle: 'completions', model: 'test-model' }} }} }}, null, (response) => response && response.error ? reject(new Error(response.error)) : resolve(response));
        }}).then((response) => {{
          return waitFor(() => planningFetchStarted).then(() => response);
        }}).then((response) => {{
          return new Promise((resolve, reject) => {{
            listener({{ type: 'cancel-active-job' }}, null, (cancelResponse) => cancelResponse && cancelResponse.error ? reject(new Error(cancelResponse.error)) : resolve({{ response, cancelResponse }}));
          }});
        }}).then((pair) => {{
          return waitFor(() => storage.bookmarkAdvisorActiveJob && storage.bookmarkAdvisorActiveJob.status !== 'running').then(() => pair);
        }}).then((pair) => {{
          console.log(JSON.stringify({{
            startedStatus: pair.response.job.status,
            cancelResponse: pair.cancelResponse,
            finalStatus: storage.bookmarkAdvisorActiveJob.status,
            finalProgress: storage.bookmarkAdvisorActiveJob.progress,
            finalError: storage.bookmarkAdvisorActiveJob.error,
            planningSignalAborted,
            progressCleared: storage.bookmarkAdvisorProgress === null
          }}));
        }}).catch((error) => {{
          console.error(error && error.stack ? error.stack : String(error));
          process.exit(1);
        }});
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["startedStatus"], "running")
        self.assertEqual(result["cancelResponse"], {"cancelled": True})
        self.assertEqual(result["finalStatus"], "failed")
        self.assertEqual(result["finalProgress"], "Cancelled by user.")
        self.assertEqual(result["finalError"], "Cancelled by user.")
        self.assertEqual(result["planningSignalAborted"], True)
        self.assertEqual(result["progressCleared"], True)

    def test_startup_cleanup_fails_stale_running_job_on_load(self):
        script = f"""
        const path = require('path');
        const repoRoot = {json.dumps(str(_REPO_ROOT))};
        const serviceWorkerPath = {json.dumps(str(_SERVICE_WORKER))};
        const storage = {{ bookmarkAdvisorActiveJob: {{ id: 'job-stale', type: 'generate-ai-plan', status: 'running', started_at: new Date().toISOString(), updated_at: 'not-a-date' }} }};
        global.importScripts = function (...files) {{
          for (const file of files) {{ require(path.join(repoRoot, 'extension', file)); }}
        }};
        global.chrome = {{
          runtime: {{ id: 'test-extension', lastError: null, getURL: (file) => `chrome-extension://test/${{file}}`, onMessage: {{ addListener: () => {{}} }} }},
          storage: {{ local: {{
            set: (value, callback) => {{ Object.assign(storage, value); if (callback) callback(); }},
            get: (key, callback) => callback({{ [key]: storage[key] }}),
            remove: (_key, callback) => {{ if (callback) callback(); }}
          }} }},
          bookmarks: {{ getTree: () => {{ throw new Error('startup cleanup should not touch bookmarks'); }} }}
        }};
        require(serviceWorkerPath);
        setTimeout(() => {{
          console.log(JSON.stringify({{
            status: storage.bookmarkAdvisorActiveJob.status,
            progress: storage.bookmarkAdvisorActiveJob.progress,
            error: storage.bookmarkAdvisorActiveJob.error,
            startedAt: storage.bookmarkAdvisorActiveJob.started_at,
            finishedAt: storage.bookmarkAdvisorActiveJob.finished_at
          }}));
        }}, 25);
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["progress"], "Service worker restarted. Background job was interrupted.")
        self.assertEqual(result["error"], "Service worker restarted. Background job was interrupted.")
        self.assertTrue(str(result["startedAt"]))
        self.assertTrue(str(result["finishedAt"]))

    def test_startup_cleanup_leaves_fresh_running_job_untouched(self):
        script = f"""
        const path = require('path');
        const repoRoot = {json.dumps(str(_REPO_ROOT))};
        const serviceWorkerPath = {json.dumps(str(_SERVICE_WORKER))};
        const staleStartedAt = new Date(Date.now() - 120000).toISOString();
        const freshUpdatedAt = new Date().toISOString();
        const storage = {{ bookmarkAdvisorActiveJob: {{ id: 'job-fresh', type: 'generate-ai-plan', status: 'running', started_at: staleStartedAt, updated_at: freshUpdatedAt }} }};
        global.importScripts = function (...files) {{
          for (const file of files) {{ require(path.join(repoRoot, 'extension', file)); }}
        }};
        global.chrome = {{
          runtime: {{ id: 'test-extension', lastError: null, getURL: (file) => `chrome-extension://test/${{file}}`, onMessage: {{ addListener: () => {{}} }} }},
          storage: {{ local: {{
            set: (value, callback) => {{ Object.assign(storage, value); if (callback) callback(); }},
            get: (key, callback) => callback({{ [key]: storage[key] }}),
            remove: (_key, callback) => {{ if (callback) callback(); }}
          }} }},
          bookmarks: {{ getTree: () => {{ throw new Error('startup cleanup should not touch bookmarks'); }} }}
        }};
        require(serviceWorkerPath);
        setTimeout(() => {{
          console.log(JSON.stringify({{
            status: storage.bookmarkAdvisorActiveJob.status,
            progress: storage.bookmarkAdvisorActiveJob.progress,
            error: storage.bookmarkAdvisorActiveJob.error,
            startedAt: storage.bookmarkAdvisorActiveJob.started_at,
            updatedAt: storage.bookmarkAdvisorActiveJob.updated_at
          }}));
        }}, 25);
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["status"], "running")
        self.assertNotEqual(result.get("progress"), "Service worker restarted. Background job was interrupted.")
        self.assertIsNone(result.get("error"))
        self.assertTrue(str(result["startedAt"]))
        self.assertTrue(str(result["updatedAt"]))

    def test_get_active_job_consumes_late_persisted_offscreen_result(self):
        script = f"""
        const path = require('path');
        const repoRoot = {json.dumps(str(_REPO_ROOT))};
        const serviceWorkerPath = {json.dumps(str(_SERVICE_WORKER))};
        const storage = {{ bookmarkAdvisorActiveJob: {{ id: 'job-late', type: 'generate-ai-plan', status: 'running', started_at: new Date().toISOString(), updated_at: new Date().toISOString(), stage: 'llm' }} }};
        let listener = null;
        global.importScripts = function (...files) {{
          for (const file of files) {{ require(path.join(repoRoot, 'extension', file)); }}
        }};
        global.chrome = {{
          runtime: {{ id: 'test-extension', lastError: null, getURL: (file) => `chrome-extension://test/${{file}}`, onMessage: {{ addListener: (callback) => {{ listener = callback; }} }} }},
          storage: {{ local: {{
            set: (value, callback) => {{ Object.assign(storage, value); if (callback) callback(); }},
            get: (key, callback) => callback({{ [key]: storage[key] }}),
            remove: (key, callback) => {{ delete storage[key]; if (callback) callback(); }}
          }} }},
          bookmarks: {{ getTree: () => {{ throw new Error('late offscreen recovery should not touch bookmarks'); }} }}
        }};
        require(serviceWorkerPath);
        setTimeout(() => {{
          storage.bookmarkAdvisorOffscreenResult = {{
            jobId: 'job-late',
            ok: true,
            result: {{ reviewed_plan: {{ actions: [{{ action_type: 'move_bookmark' }}] }} }},
            timestamp: Date.now()
          }};
          listener({{ type: 'get-active-job' }}, null, (response) => {{
            console.log(JSON.stringify({{
              status: response.job.status,
              progress: response.job.progress,
              savedActionType: storage.bookmarkAdvisorLastPlan.plan.actions[0].action_type,
              resultCleared: !storage.bookmarkAdvisorOffscreenResult
            }}));
          }});
        }}, 25);
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["progress"], "Restored from offscreen after popup wake.")
        self.assertEqual(result["savedActionType"], "move_bookmark")
        self.assertEqual(result["resultCleared"], True)

    def test_cancel_requested_stops_reviewed_plan_before_remaining_actions(self):
        script = f"""
        const path = require('path');
        const repoRoot = {json.dumps(str(_REPO_ROOT))};
        const serviceWorkerPath = {json.dumps(str(_SERVICE_WORKER))};
        const storage = {{}};
        let listener = null;
        let moveCalls = [];
        let firstMovePending = true;
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
            get: (id, callback) => callback({{
              '10': [{{ id: '10', title: 'Example 1', url: 'https://example.com', parentId: '1' }}],
              '11': [{{ id: '11', title: 'Example 2', url: 'https://example.com', parentId: '1' }}],
              '1': [{{ id: '1', title: '收藏夹栏', parentId: '0' }}]
            }}[id] || []),
            getTree: (callback) => callback([{{ id: '0', title: '', children: [{{ id: '1', title: '收藏夹栏', children: [{{ id: '10', title: 'Example 1', url: 'https://example.com' }}, {{ id: '11', title: 'Example 2', url: 'https://example.com' }}] }}] }}]),
            getChildren: (_id, callback) => callback([]),
            create: (opts, callback) => callback({{ id: 'c1', title: opts.title, parentId: opts.parentId }}),
            move: (id, opts, callback) => {{
              moveCalls.push({{ id, parentId: opts.parentId }});
              if (firstMovePending) {{
                firstMovePending = false;
                setTimeout(() => {{ if (callback) callback(); }}, 30);
                return;
              }}
              if (callback) callback();
            }}
          }}
        }};
        function waitFor(predicate, deadlineMs = 1000) {{
          const deadline = Date.now() + deadlineMs;
          return new Promise((resolve, reject) => {{
            function tick() {{
              if (predicate()) {{
                resolve();
                return;
              }}
              if (Date.now() > deadline) {{
                reject(new Error('timed out waiting for condition'));
                return;
              }}
              setTimeout(tick, 5);
            }}
            tick();
          }});
        }}
        require(serviceWorkerPath);
        new Promise((resolve, reject) => {{
          listener({{ type: 'start-background-job', job_type: 'apply-reviewed-plan', payload: {{ plan: {{ actions: [{{
            action_id: 'a-1',
            action_type: 'move_bookmark',
            status: 'approved',
            reason: 'move one',
            confidence: 0.9,
            bookmark_locator: {{ id: '10', title: 'Example 1', url: 'https://example.com', normalized_url: 'https://example.com/', folder_path: '/收藏夹栏' }},
            from_path: '/收藏夹栏',
            to_path: '/收藏夹栏/AI'
          }}, {{
            action_id: 'a-2',
            action_type: 'move_bookmark',
            status: 'approved',
            reason: 'move two',
            confidence: 0.9,
            bookmark_locator: {{ id: '11', title: 'Example 2', url: 'https://example.com', normalized_url: 'https://example.com/', folder_path: '/收藏夹栏' }},
            from_path: '/收藏夹栏',
            to_path: '/收藏夹栏/AI'
          }}] }} }} }}, null, (response) => response && response.error ? reject(new Error(response.error)) : resolve(response));
        }}).then((response) => {{
          return waitFor(() => moveCalls.length === 1).then(() => response);
        }}).then((response) => {{
          return new Promise((resolve, reject) => {{
            listener({{ type: 'cancel-active-job' }}, null, (cancelResponse) => cancelResponse && cancelResponse.error ? reject(new Error(cancelResponse.error)) : resolve({{ response, cancelResponse }}));
          }});
        }}).then((pair) => {{
          return waitFor(() => storage.bookmarkAdvisorActiveJob && storage.bookmarkAdvisorActiveJob.status !== 'running').then(() => pair);
        }}).then((pair) => {{
          console.log(JSON.stringify({{
            startedStatus: pair.response.job.status,
            cancelResponse: pair.cancelResponse,
            finalStatus: storage.bookmarkAdvisorActiveJob.status,
            finalProgress: storage.bookmarkAdvisorActiveJob.progress,
            finalError: storage.bookmarkAdvisorActiveJob.error,
            cancellationRequestedAt: storage.bookmarkAdvisorActiveJob.cancellation_requested_at,
            moveCalls
          }}));
        }}).catch((error) => {{
          console.error(error && error.stack ? error.stack : String(error));
          process.exit(1);
        }});
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["startedStatus"], "running")
        self.assertEqual(result["cancelResponse"], {"cancelled": True})
        self.assertEqual(result["finalStatus"], "failed")
        self.assertEqual(result["finalProgress"], "Cancelled by user.")
        self.assertEqual(result["finalError"], "Cancelled by user.")
        self.assertTrue(str(result["cancellationRequestedAt"]))
        self.assertEqual(len(cast(list[object], result["moveCalls"])), 1)

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
          bookmark_locator: {{ id: '10', title: 'Example', url: 'https://example.com', normalized_url: 'https://example.com/', folder_path: '/收藏夹栏' }},
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
          bookmark_locator: {{ id: '10', title: 'Example', url: 'https://example.com', normalized_url: 'https://example.com/', folder_path: '/收藏夹栏' }}
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
        let moveCalls = [];
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
            get: (id, callback) => callback(id === '1' ? [{{ id: '1', title: '收藏夹栏', children: [] }}] : id === '99' ? [{{ id: '99', title: 'Example', url: 'https://example.com', parentId: '1' }}] : []),
            search: (_query, callback) => callback([{{ id: '99', title: 'Example', url: 'https://example.com', parentId: '1' }}]),
            getTree: (callback) => callback([{{ id: '0', title: '', children: [{{ id: '1', title: '收藏夹栏', children: [{{ id: '99', title: 'Example', url: 'https://example.com' }}] }}] }}]),
            getChildren: (_id, callback) => callback([]),
            create: (opts, callback) => callback({{ id: 'q1', title: opts.title, parentId: opts.parentId }}),
            move: (id, opts, callback) => {{ moveCalls.push({{ id, parentId: opts.parentId }}); if (callback) callback(); }}
          }}
        }};
        require(serviceWorkerPath);
        listener({{ type: 'apply-reviewed-plan', plan: {{ actions: [{{
          action_id: 'a-1',
          action_type: 'remove_duplicate',
          status: 'approved',
          reason: 'dedupe',
          confidence: 0.9,
          bookmark_locator: {{ id: '10', title: 'Example', url: 'https://example.com', normalized_url: 'https://example.com/', folder_path: '/收藏夹栏' }}
        }}] }} }}, null, (response) => {{
          console.log(JSON.stringify({{ succeeded: response.succeeded.length, failures: response.failures.length, moveCalls }}));
        }});
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["failures"], 0)
        self.assertEqual(result["moveCalls"], [{"id": "99", "parentId": "q1"}])
    def test_policy_blocks_action_outside_focus_path(self):
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
            set: (value, callback) => {{ Object.assign(storage, value); if (callback) callback(); }},
            get: (key, callback) => callback({{ [key]: storage[key] }}),
            remove: (_key, callback) => {{ if (callback) callback(); }}
          }} }},
          bookmarks: {{
            getTree: (callback) => callback([{{ id: '0', title: '', children: [] }}])
          }}
        }};
        require(serviceWorkerPath);
        listener({{ type: 'apply-reviewed-plan', focusPath: '/收藏夹栏/AI', plan: {{ actions: [{{
          action_id: 'a-1',
          action_type: 'move_bookmark',
          status: 'approved',
          reason: 'move it',
          confidence: 0.9,
          bookmark_locator: {{ id: '10', title: 'Example', url: 'https://example.com', normalized_url: 'https://example.com/', folder_path: '/收藏夹栏' }},
          from_path: '/收藏夹栏',
          to_path: '/收藏夹栏/AI'
        }}] }} }}, null, (response) => {{
          console.log(JSON.stringify({{
            failures: response.failures.length,
            error: response.failures[0].error
          }}));
        }});
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["failures"], 1)
        self.assertIn("outside focus scope", str(result["error"]))

    def test_policy_allows_action_within_focus_path(self):
        script = f"""
        const path = require('path');
        const repoRoot = {json.dumps(str(_REPO_ROOT))};
        const serviceWorkerPath = {json.dumps(str(_SERVICE_WORKER))};
        const storage = {{}};
        let listener = null;
        let moveCalls = [];
        const nodes = {{
          '10': {{ id: '10', title: 'Example', url: 'https://example.com', parentId: '2' }},
          '2': {{ id: '2', title: 'AI', parentId: '1' }},
          '1': {{ id: '1', title: '收藏夹栏', parentId: '0' }}
        }};
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
            get: (id, callback) => callback(nodes[id] ? [nodes[id]] : []),
            getTree: (callback) => callback([{{ id: '0', title: '', children: [{{ id: '1', title: '收藏夹栏', children: [{{ id: '2', title: 'AI', children: [{{ id: '10', title: 'Example', url: 'https://example.com' }}] }}] }}] }}]),
            getChildren: (_id, callback) => callback([]),
            create: (opts, callback) => callback({{ id: 'c1', title: opts.title, parentId: opts.parentId }}),
            move: (id, opts, callback) => {{ moveCalls.push({{ id, parentId: opts.parentId }}); if (callback) callback(); }}
          }}
        }};
        require(serviceWorkerPath);
        listener({{ type: 'apply-reviewed-plan', focusPath: '/收藏夹栏/AI', plan: {{ actions: [{{
          action_id: 'a-1',
          action_type: 'move_bookmark',
          status: 'approved',
          reason: 'move it',
          confidence: 0.9,
          bookmark_locator: {{ id: '10', title: 'Example', url: 'https://example.com', normalized_url: 'https://example.com/', folder_path: '/收藏夹栏/AI' }},
          from_path: '/收藏夹栏/AI',
          to_path: '/收藏夹栏/AI/Tools'
        }}] }} }}, null, (response) => {{
          console.log(JSON.stringify({{ succeeded: response.succeeded.length, failures: response.failures.length, moveCalls }}));
        }});
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["failures"], 0)
        self.assertEqual(len(cast(list[object], result["moveCalls"])), 1)

    def test_policy_allows_all_when_focus_path_is_empty(self):
        script = f"""
        const path = require('path');
        const repoRoot = {json.dumps(str(_REPO_ROOT))};
        const serviceWorkerPath = {json.dumps(str(_SERVICE_WORKER))};
        const storage = {{}};
        let listener = null;
        let moveCalls = [];
        const nodes = {{
          '10': {{ id: '10', title: 'Example', url: 'https://example.com', parentId: '1' }},
          '1': {{ id: '1', title: '收藏夹栏', parentId: '0' }}
        }};
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
            get: (id, callback) => callback(nodes[id] ? [nodes[id]] : []),
            getTree: (callback) => callback([{{ id: '0', title: '', children: [{{ id: '1', title: '收藏夹栏', children: [{{ id: '10', title: 'Example', url: 'https://example.com' }}] }}] }}]),
            getChildren: (_id, callback) => callback([]),
            create: (opts, callback) => callback({{ id: 'c1', title: opts.title, parentId: opts.parentId }}),
            move: (id, opts, callback) => {{ moveCalls.push({{ id, parentId: opts.parentId }}); if (callback) callback(); }}
          }}
        }};
        require(serviceWorkerPath);
        listener({{ type: 'apply-reviewed-plan', plan: {{ actions: [{{
          action_id: 'a-1',
          action_type: 'move_bookmark',
          status: 'approved',
          reason: 'move it',
          confidence: 0.9,
          bookmark_locator: {{ id: '10', title: 'Example', url: 'https://example.com', normalized_url: 'https://example.com/', folder_path: '/收藏夹栏' }},
          from_path: '/收藏夹栏',
          to_path: '/收藏夹栏/AI'
        }}] }} }}, null, (response) => {{
          console.log(JSON.stringify({{ succeeded: response.succeeded.length, failures: response.failures.length, moveCalls }}));
        }});
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["failures"], 0)
        self.assertEqual(len(cast(list[object], result["moveCalls"])), 1)

    def test_remove_duplicate_moves_to_quarantine_not_delete(self):
        script = f"""
        const path = require('path');
        const repoRoot = {json.dumps(str(_REPO_ROOT))};
        const serviceWorkerPath = {json.dumps(str(_SERVICE_WORKER))};
        const storage = {{}};
        let listener = null;
        let moveCalls = [];
        let removeCalls = 0;
        const nodes = {{
          '10': {{ id: '10', title: 'Example', url: 'https://example.com', parentId: '1' }},
          '1': {{ id: '1', title: '收藏夹栏', parentId: '0' }}
        }};
        global.importScripts = function (...files) {{
          for (const file of files) {{ require(path.join(repoRoot, 'extension', file)); }}
        }};
        global.chrome = {{
          runtime: {{ id: 'test-extension', lastError: null, getURL: (file) => `chrome-extension://test/${{file}}`, onMessage: {{ addListener: (callback) => {{ listener = callback; }} }} }},
          storage: {{ local: {{
            set: (value, callback) => {{ Object.assign(storage, value); if (callback) callback(); }},
            get: (key, callback) => callback({{ [key]: storage[key] }}),
            remove: (_key, callback) => {{ removeCalls += 1; if (callback) callback(); }}
          }} }},
          bookmarks: {{
            get: (id, callback) => callback(nodes[id] ? [nodes[id]] : []),
            getTree: (callback) => callback([{{ id: '0', title: '', children: [{{ id: '1', title: '收藏夹栏', children: [{{ id: '10', title: 'Example', url: 'https://example.com' }}] }}] }}]),
            getChildren: (_id, callback) => callback([]),
            create: (opts, callback) => callback({{ id: 'q1', title: opts.title, parentId: opts.parentId }}),
            move: (id, opts, callback) => {{ moveCalls.push({{ id, parentId: opts.parentId }}); if (callback) callback(); }}
          }}
        }};
        require(serviceWorkerPath);
        listener({{ type: 'apply-reviewed-plan', plan: {{ actions: [{{
          action_id: 'a-1',
          action_type: 'remove_duplicate',
          status: 'approved',
          reason: 'dedupe',
          confidence: 0.9,
          bookmark_locator: {{ id: '10', title: 'Example', url: 'https://example.com', normalized_url: 'https://example.com/', folder_path: '/收藏夹栏' }}
        }}] }} }}, null, (response) => {{
          console.log(JSON.stringify({{ succeeded: response.succeeded.length, removeCalls, moveCalls }}));
        }});
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["removeCalls"], 0)
        self.assertEqual(result["moveCalls"], [{"id": "10", "parentId": "q1"}])

    def test_undo_log_records_before_state_for_move(self):
        script = f"""
        const path = require('path');
        const repoRoot = {json.dumps(str(_REPO_ROOT))};
        const serviceWorkerPath = {json.dumps(str(_SERVICE_WORKER))};
        const storage = {{}};
        let listener = null;
        const nodes = {{
          '10': {{ id: '10', title: 'Example', url: 'https://example.com', parentId: '1' }},
          '1': {{ id: '1', title: '收藏夹栏', parentId: '0' }}
        }};
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
            get: (id, callback) => callback(nodes[id] ? [nodes[id]] : []),
            getTree: (callback) => callback([{{ id: '0', title: '', children: [{{ id: '1', title: '收藏夹栏', children: [{{ id: '10', title: 'Example', url: 'https://example.com' }}] }}] }}]),
            getChildren: (_id, callback) => callback([]),
            create: (opts, callback) => callback({{ id: 'c1', title: opts.title, parentId: opts.parentId }}),
            move: (_id, _opts, callback) => {{ if (callback) callback(); }}
          }}
        }};
        require(serviceWorkerPath);
        listener({{ type: 'apply-reviewed-plan', plan: {{ actions: [{{
          action_id: 'a-1',
          action_type: 'move_bookmark',
          status: 'approved',
          reason: 'move it',
          confidence: 0.9,
          bookmark_locator: {{ id: '10', title: 'Example', url: 'https://example.com', normalized_url: 'https://example.com/', folder_path: '/收藏夹栏' }},
          from_path: '/收藏夹栏',
          to_path: '/收藏夹栏/AI'
        }}] }} }}, null, (response) => {{
          const undoLog = storage.bookmarkAdvisorUndoLog || [];
          console.log(JSON.stringify({{
            succeeded: response.succeeded.length,
            logLength: undoLog.length,
            beforeParentId: undoLog[0] && undoLog[0].before.parentId,
            undoType: undoLog[0] && undoLog[0].undo_action.type,
            undoParentId: undoLog[0] && undoLog[0].undo_action.parentId
          }}));
        }});
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["logLength"], 1)
        self.assertEqual(result["beforeParentId"], "1")
        self.assertEqual(result["undoType"], "move")
        self.assertEqual(result["undoParentId"], "1")

    def test_undo_last_execution_reverses_move(self):
        script = f"""
        const path = require('path');
        const repoRoot = {json.dumps(str(_REPO_ROOT))};
        const serviceWorkerPath = {json.dumps(str(_SERVICE_WORKER))};
        const storage = {{}};
        let listener = null;
        let undoMoveCalls = [];
        const nodes = {{
          '10': {{ id: '10', title: 'Example', url: 'https://example.com', parentId: '1' }},
          '1': {{ id: '1', title: '收藏夹栏', parentId: '0' }}
        }};
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
            get: (id, callback) => callback(nodes[id] ? [nodes[id]] : []),
            getTree: (callback) => callback([{{ id: '0', title: '', children: [{{ id: '1', title: '收藏夹栏', children: [{{ id: '10', title: 'Example', url: 'https://example.com' }}] }}] }}]),
            getChildren: (_id, callback) => callback([]),
            create: (opts, callback) => callback({{ id: 'c1', title: opts.title, parentId: opts.parentId }}),
            move: (id, opts, callback) => {{ undoMoveCalls.push({{ id, parentId: opts.parentId }}); if (callback) callback(); }}
          }}
        }};
        require(serviceWorkerPath);
        new Promise((resolve) => {{
          listener({{ type: 'apply-reviewed-plan', plan: {{ actions: [{{
            action_id: 'a-1',
            action_type: 'move_bookmark',
            status: 'approved',
            reason: 'move it',
            confidence: 0.9,
            bookmark_locator: {{ id: '10', title: 'Example', url: 'https://example.com', normalized_url: 'https://example.com/', folder_path: '/收藏夹栏' }},
            from_path: '/收藏夹栏',
            to_path: '/收藏夹栏/AI'
          }}] }} }}, null, () => resolve());
        }}).then(() => new Promise((resolve) => {{
          listener({{ type: 'undo-last-execution' }}, null, (response) => resolve(response));
        }})).then((response) => {{
          console.log(JSON.stringify({{
            undone: response.undone,
            count: response.count,
            undoMoveCalls: undoMoveCalls.length,
            restoredTo: undoMoveCalls[1] && undoMoveCalls[1].parentId
          }}));
        }}).catch((error) => {{
          console.error(error && error.stack ? error.stack : String(error));
          process.exit(1);
        }});
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["undone"], True)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["undoMoveCalls"], 2)
        self.assertEqual(result["restoredTo"], "1")

    def test_agreed_keep_for_review_executes_as_noop_report_entry(self):
        script = f"""
        const path = require('path');
        const repoRoot = {json.dumps(str(_REPO_ROOT))};
        const serviceWorkerPath = {json.dumps(str(_SERVICE_WORKER))};
        const storage = {{}};
        let listener = null;
        let bookmarkMutations = 0;
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
            getTree: (callback) => callback([{{ id: '0', title: '', children: [] }}]),
            create: () => {{ bookmarkMutations += 1; throw new Error('noop should not mutate'); }},
            move: () => {{ bookmarkMutations += 1; throw new Error('noop should not mutate'); }},
            update: () => {{ bookmarkMutations += 1; throw new Error('noop should not mutate'); }},
            remove: () => {{ bookmarkMutations += 1; throw new Error('noop should not mutate'); }}
          }}
        }};
        require(serviceWorkerPath);
        listener({{ type: 'apply-reviewed-plan', plan: {{ actions: [{{
          action_id: 'a-1',
          action_type: 'keep_for_review',
          status: 'approved',
          reason: 'reviewed and intentionally left unchanged',
          confidence: 0.3,
          bookmark_locator: {{ id: '10', title: 'Example', url: 'https://example.com' }},
          details: {{ review_agreed: true }}
        }}] }} }}, null, (response) => {{
          console.log(JSON.stringify({{
            succeeded: response.succeeded.length,
            failures: response.failures.length,
            actionType: response.succeeded[0] && response.succeeded[0].actionType,
            bookmarkMutations,
            undoLogLength: (storage.bookmarkAdvisorUndoLog || []).length
          }}));
        }});
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["failures"], 0)
        self.assertEqual(result["actionType"], "keep_for_review")
        self.assertEqual(result["bookmarkMutations"], 0)
        self.assertEqual(result["undoLogLength"], 0)

    def test_delete_empty_folder_removes_only_empty_folder_and_records_undo(self):
        script = f"""
        const path = require('path');
        const repoRoot = {json.dumps(str(_REPO_ROOT))};
        const serviceWorkerPath = {json.dumps(str(_SERVICE_WORKER))};
        const storage = {{}};
        let listener = null;
        const removed = [];
        const nodes = {{
          '1': {{ id: '1', title: '收藏夹栏', parentId: '0' }},
          '20': {{ id: '20', title: 'Empty', parentId: '1' }}
        }};
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
            get: (id, callback) => callback(nodes[id] ? [nodes[id]] : []),
            getChildren: (id, callback) => callback(id === '20' ? [] : [nodes['20']]),
            getTree: (callback) => callback([{{ id: '0', title: '', children: [{{ id: '1', title: '收藏夹栏', children: [{{ id: '20', title: 'Empty', children: [] }}] }}] }}]),
            remove: (id, callback) => {{ removed.push(id); if (callback) callback(); }}
          }}
        }};
        require(serviceWorkerPath);
        listener({{ type: 'apply-reviewed-plan', plan: {{ actions: [{{
          action_id: 'a-1',
          action_type: 'delete_empty_folder',
          status: 'approved',
          reason: 'empty folder no longer needed',
          confidence: 0.9,
          folder_locator: {{ id: '20', name: 'Empty', path: '/收藏夹栏/Empty' }},
          from_path: '/收藏夹栏/Empty'
        }}] }} }}, null, (response) => {{
          const undoLog = storage.bookmarkAdvisorUndoLog || [];
          console.log(JSON.stringify({{
            succeeded: response.succeeded.length,
            failures: response.failures.length,
            removed,
            undoType: undoLog[0] && undoLog[0].undo_action.type,
            undoPath: undoLog[0] && undoLog[0].undo_action.path
          }}));
        }});
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["succeeded"], 1)
        self.assertEqual(result["failures"], 0)
        self.assertEqual(result["removed"], ["20"])
        self.assertEqual(result["undoType"], "create_folder")
        self.assertEqual(result["undoPath"], "/收藏夹栏/Empty")

    def test_delete_empty_folder_rejects_non_empty_folder(self):
        script = f"""
        const path = require('path');
        const repoRoot = {json.dumps(str(_REPO_ROOT))};
        const serviceWorkerPath = {json.dumps(str(_SERVICE_WORKER))};
        const storage = {{}};
        let listener = null;
        let removeCalls = 0;
        const nodes = {{
          '1': {{ id: '1', title: '收藏夹栏', parentId: '0' }},
          '20': {{ id: '20', title: 'Not Empty', parentId: '1' }}
        }};
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
            get: (id, callback) => callback(nodes[id] ? [nodes[id]] : []),
            getChildren: (id, callback) => callback(id === '20' ? [{{ id: '30', title: 'Child', url: 'https://example.com' }}] : [nodes['20']]),
            getTree: (callback) => callback([{{ id: '0', title: '', children: [{{ id: '1', title: '收藏夹栏', children: [{{ id: '20', title: 'Not Empty', children: [{{ id: '30', title: 'Child', url: 'https://example.com' }}] }}] }}] }}]),
            remove: (_id, callback) => {{ removeCalls += 1; if (callback) callback(); }}
          }}
        }};
        require(serviceWorkerPath);
        listener({{ type: 'apply-reviewed-plan', plan: {{ actions: [{{
          action_id: 'a-1',
          action_type: 'delete_empty_folder',
          status: 'approved',
          reason: 'try delete',
          confidence: 0.9,
          folder_locator: {{ id: '20', name: 'Not Empty', path: '/收藏夹栏/Not Empty' }},
          from_path: '/收藏夹栏/Not Empty'
        }}] }} }}, null, (response) => {{
          console.log(JSON.stringify({{
            succeeded: response.succeeded.length,
            failures: response.failures.length,
            error: response.failures[0] && response.failures[0].error,
            removeCalls
          }}));
        }});
        """
        result = cast(dict[str, object], self._node_script(script))
        self.assertEqual(result["succeeded"], 0)
        self.assertEqual(result["failures"], 1)
        self.assertIn("requires the folder to be empty", str(result["error"]))
        self.assertEqual(result["removeCalls"], 0)


if __name__ == "__main__":
    _ = unittest.main()
