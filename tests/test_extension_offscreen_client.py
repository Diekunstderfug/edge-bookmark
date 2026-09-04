"""Independent tests for the extracted MV3 offscreen transport."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EXTENSION = ROOT / "extension"


class ExtensionOffscreenClientTest(unittest.TestCase):
    def _node_eval(self, body: str) -> Any:
        script = f"""
          require({json.dumps(str(EXTENSION / 'background' / 'offscreen_client.js'))});
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
        )
        output = completed.stdout.strip().splitlines()
        self.assertTrue(output, completed.stderr)
        return json.loads(output[-1])

    def test_document_lifecycle_deduplicates_creation_and_supports_legacy_probe(self) -> None:
        result = self._node_eval(
            """
            const factory = BookmarkAdvisor.Background.OffscreenClient;
            let exists = false;
            let releaseCreation;
            const creationGate = new Promise((resolve) => { releaseCreation = resolve; });
            const createCalls = [];
            const contextQueries = [];
            let closeCalls = 0;
            const chrome = {
              runtime: {
                getURL: (path) => `chrome-extension://test/${path}`,
                getContexts: async (query) => {
                  contextQueries.push(query);
                  return exists ? [{ contextType: 'OFFSCREEN_DOCUMENT' }] : [];
                },
                sendMessage: async () => ({ ok: true }),
              },
              offscreen: {
                createDocument: async (options) => {
                  createCalls.push(options);
                  await creationGate;
                  exists = true;
                },
                closeDocument: async () => { closeCalls += 1; exists = false; },
              },
            };
            const storage = { get: async () => null, remove: async () => {} };
            const client = factory.create({ chrome, storage });
            const before = await client.hasDocument();
            const first = client.ensureDocument();
            const second = client.ensureDocument();
            while (createCalls.length === 0) await Promise.resolve();
            releaseCreation();
            const ensured = await Promise.all([first, second]);
            const after = await client.hasDocument();
            const closed = await client.closeDocument();

            const legacyClient = factory.create({
              chrome: {
                runtime: { sendMessage: async () => ({ ok: true }) },
                offscreen: {
                  createDocument: async () => {},
                  hasDocument: async () => true,
                },
              },
              storage,
            });
            console.log(JSON.stringify({
              supports: client.supports(), before, ensured, after, closed,
              createCalls, closeCalls, contextQueries,
              legacySupports: legacyClient.supports(),
              legacyHasDocument: await legacyClient.hasDocument(),
            }));
            """
        )
        self.assertTrue(result["supports"])
        self.assertFalse(result["before"])
        self.assertEqual(result["ensured"], [True, True])
        self.assertTrue(result["after"])
        self.assertTrue(result["closed"])
        self.assertEqual(len(result["createCalls"]), 1)
        self.assertEqual(
            result["createCalls"][0],
            {
                "url": "offscreen.html",
                "reasons": ["WORKERS"],
                "justification": "Execute long-running LLM API calls that exceed MV3 Service Worker idle timeout.",
            },
        )
        self.assertEqual(result["closeCalls"], 1)
        self.assertEqual(
            result["contextQueries"][0]["documentUrls"],
            ["chrome-extension://test/offscreen.html"],
        )
        self.assertTrue(result["legacySupports"])
        self.assertTrue(result["legacyHasDocument"])

    def test_hard_timeout_budget_is_mode_aware_and_precedes_stale_detection(self) -> None:
        result = self._node_eval(
            """
            const factory = BookmarkAdvisor.Background.OffscreenClient;
            const client = factory.create({
              chrome: { runtime: { sendMessage: async () => ({ ok: true }) } },
              storage: { get: async () => null, remove: async () => {} },
              activeJobStaleMs: 30 * 60 * 1000,
            });
            const staleMs = factory.DEFAULT_ACTIVE_JOB_STALE_MS;
            const defaultBudget = client.hardTimeoutMs('generate', {});
            const maxRetryBudget = client.hardTimeoutMs('generate', { maxRetries: 3 });
            const longRequestBudget = client.hardTimeoutMs('generate', {
              requestTimeoutMs: 300000, maxRetries: 3,
            });

            const small = factory.create({
              chrome: { runtime: { sendMessage: async () => ({ ok: true }) } },
              storage: { get: async () => null, remove: async () => {} },
              activeJobStaleMs: 100,
              staleSafetyMarginMs: 10,
              deadlineGraceMs: 0,
              aiEndpoint: { DEFAULT_REQUEST_TIMEOUT_MS: 20, MAX_REQUEST_TIMEOUT_MS: 50 },
            });
            const counted = factory.create({
              chrome: { runtime: { sendMessage: async () => ({ ok: true }) } },
              storage: { get: async () => null, remove: async () => {} },
              activeJobStaleMs: 100,
              staleSafetyMarginMs: 10,
              deadlineGraceMs: 0,
              aiEndpoint: {
                DEFAULT_REQUEST_TIMEOUT_MS: 20,
                MAX_REQUEST_TIMEOUT_MS: 50,
                requestAttemptCount: () => 4,
              },
            });
            console.log(JSON.stringify({
              staleMs, defaultBudget, maxRetryBudget, longRequestBudget,
              reviseNested: small.hardTimeoutMs('revise', {
                requestTimeoutMs: 1,
                options: { requestTimeoutMs: 5, maxRetries: 0 },
              }),
              generateTopLevel: small.hardTimeoutMs('generate', {
                requestTimeoutMs: 5, maxRetries: 0,
              }),
              attemptCounted: counted.hardTimeoutMs('generate', {
                requestTimeoutMs: 5, maxRetries: 0,
              }),
            }));
            """
        )
        stale_ms = result["staleMs"]
        self.assertLess(result["defaultBudget"], stale_ms)
        self.assertLess(result["maxRetryBudget"], stale_ms)
        self.assertLess(result["longRequestBudget"], stale_ms)
        self.assertEqual(result["reviseNested"], 10)
        self.assertEqual(result["generateTopLevel"], 10)
        # 4 个端点回退 × 2 × 5ms 单路径预算 = 40ms：锁定 endpointAttempts 因子。
        self.assertEqual(result["attemptCounted"], 40)
        # 默认 auto 风格（5 端点回退）下单路径预算远超 stale 上限，应被截断而非缩水。
        self.assertEqual(result["defaultBudget"], stale_ms - 60 * 1000)

    def test_run_routes_only_matching_job_messages_and_removes_listener(self) -> None:
        result = self._node_eval(
            """
            const listeners = new Set();
            const sent = [];
            const clearedTimers = [];
            const timers = new Map();
            let nextTimerId = 1;
            const chrome = {
              runtime: {
                getURL: (path) => path,
                getContexts: async () => [{ contextType: 'OFFSCREEN_DOCUMENT' }],
                sendMessage: async (message) => {
                  sent.push(message);
                  if (message.type === 'offscreen-ping') {
                    return { ok: true, busy: false, jobId: null };
                  }
                  return { ok: true };
                },
                onMessage: {
                  addListener: (listener) => listeners.add(listener),
                  removeListener: (listener) => listeners.delete(listener),
                },
              },
              offscreen: { createDocument: async () => {} },
            };
            const client = BookmarkAdvisor.Background.OffscreenClient.create({
              chrome,
              storage: { get: async () => null, remove: async () => {} },
              timers: {
                setTimeout(callback, milliseconds) {
                  const id = nextTimerId++;
                  timers.set(id, { callback, milliseconds });
                  return id;
                },
                clearTimeout(id) { clearedTimers.push(id); timers.delete(id); },
              },
            });
            const progress = [];
            const runPromise = client.run(
              { id: 'job-main' },
              'generate',
              { model: 'test-model' },
              { onProgress: async (message) => progress.push(message) },
            );
            while (!sent.some((message) => message.type === 'offscreen-llm')) {
              await Promise.resolve();
            }
            for (const listener of [...listeners]) {
              listener({ type: 'offscreen-result', jobId: 'other-job', result: { ignored: true } });
              listener({ type: 'offscreen-progress', jobId: 'job-main', message: 'halfway' });
              listener({ type: 'offscreen-result', jobId: 'job-main', result: { value: 42 } });
            }
            const returned = await runPromise;
            await Promise.resolve();
            console.log(JSON.stringify({
              returned, progress,
              sentTypes: sent.map((message) => message.type),
              sentJobId: sent.find((message) => message.type === 'offscreen-llm').jobId,
              listenerCount: listeners.size,
              timerCount: timers.size,
              clearedTimers,
            }));
            """
        )
        self.assertEqual(result["returned"], {"value": 42})
        self.assertEqual(result["progress"], ["halfway"])
        self.assertEqual(result["sentTypes"], ["offscreen-ping", "offscreen-llm"])
        self.assertEqual(result["sentJobId"], "job-main")
        self.assertEqual(result["listenerCount"], 0)
        self.assertEqual(result["timerCount"], 0)
        self.assertEqual(result["clearedTimers"], [1])

    def test_abort_rejects_with_abort_error_cancels_remote_and_cleans_listener(self) -> None:
        result = self._node_eval(
            """
            const listeners = new Set();
            const sent = [];
            const chrome = {
              runtime: {
                getURL: (path) => path,
                getContexts: async () => [{ contextType: 'OFFSCREEN_DOCUMENT' }],
                sendMessage: async (message) => {
                  sent.push(message.type);
                  if (message.type === 'offscreen-ping') return { ok: true, busy: false };
                  return { ok: true };
                },
                onMessage: {
                  addListener: (listener) => listeners.add(listener),
                  removeListener: (listener) => listeners.delete(listener),
                },
              },
              offscreen: { createDocument: async () => {} },
            };
            const client = BookmarkAdvisor.Background.OffscreenClient.create({
              chrome,
              storage: { get: async () => null, remove: async () => {} },
            });
            const controller = new AbortController();
            const promise = client.run({ id: 'job-abort' }, 'generate', {}, controller);
            while (!sent.includes('offscreen-llm')) await Promise.resolve();
            controller.abort();
            let failure = null;
            try { await promise; } catch (error) {
              failure = { name: error.name, code: error.code, message: error.message };
            }
            await Promise.resolve();

            const alreadyAborted = new AbortController();
            alreadyAborted.abort();
            let preAbortedName = '';
            try {
              await client.run({ id: 'job-pre-abort' }, 'generate', {}, alreadyAborted);
            } catch (error) {
              preAbortedName = error.name;
            }
            await Promise.resolve();
            console.log(JSON.stringify({
              failure, preAbortedName, sent,
              listenerCount: listeners.size,
              preAbortedWasSent: sent.filter((type) => type === 'offscreen-llm').length > 1,
            }));
            """
        )
        self.assertEqual(
            result["failure"],
            {"name": "AbortError", "code": 20, "message": "Cancelled by user."},
        )
        self.assertEqual(result["preAbortedName"], "AbortError")
        self.assertIn("offscreen-cancel", result["sent"])
        self.assertEqual(result["listenerCount"], 0)
        self.assertFalse(result["preAbortedWasSent"])

    def test_hard_timeout_rejects_and_cleans_dynamic_listener(self) -> None:
        result = self._node_eval(
            """
            const listeners = new Set();
            const timers = new Map();
            const cleared = [];
            let nextTimerId = 1;
            const chrome = {
              runtime: {
                getURL: (path) => path,
                getContexts: async () => [{ contextType: 'OFFSCREEN_DOCUMENT' }],
                sendMessage: async (message) => message.type === 'offscreen-ping'
                  ? { ok: true, busy: false }
                  : { ok: true },
                onMessage: {
                  addListener: (listener) => listeners.add(listener),
                  removeListener: (listener) => listeners.delete(listener),
                },
              },
              offscreen: { createDocument: async () => {} },
            };
            const client = BookmarkAdvisor.Background.OffscreenClient.create({
              chrome,
              storage: { get: async () => null, remove: async () => {} },
              activeJobStaleMs: 1000,
              staleSafetyMarginMs: 100,
              deadlineGraceMs: 0,
              aiEndpoint: { DEFAULT_REQUEST_TIMEOUT_MS: 1000, MAX_REQUEST_TIMEOUT_MS: 1000 },
              timers: {
                setTimeout(callback, milliseconds) {
                  const id = nextTimerId++;
                  timers.set(id, { callback, milliseconds });
                  return id;
                },
                clearTimeout(id) { cleared.push(id); timers.delete(id); },
              },
            });
            const promise = client.run({ id: 'job-timeout' }, 'generate', {});
            while (timers.size === 0) await Promise.resolve();
            const timer = [...timers.values()][0];
            timer.callback();
            let error = '';
            try { await promise; } catch (caught) { error = caught.message; }
            console.log(JSON.stringify({
              timeoutMs: timer.milliseconds,
              error,
              listenerCount: listeners.size,
              timerCount: timers.size,
              cleared,
            }));
            """
        )
        self.assertEqual(result["timeoutMs"], 900)
        self.assertIn("did not respond", result["error"])
        self.assertEqual(result["listenerCount"], 0)
        self.assertEqual(result["timerCount"], 0)
        self.assertEqual(result["cleared"], [1])

    def test_ping_cancel_and_orphan_eviction_remain_transport_only(self) -> None:
        result = self._node_eval(
            """
            const sent = [];
            const slept = [];
            let pingResponse = { ok: true, busy: true, jobId: 'orphan-old' };
            const chrome = {
              runtime: {
                sendMessage: async (message) => {
                  sent.push(message.type);
                  return message.type === 'offscreen-ping' ? pingResponse : { ok: true };
                },
              },
            };
            const client = BookmarkAdvisor.Background.OffscreenClient.create({
              chrome,
              storage: { get: async () => null, remove: async () => {} },
              clock: { sleep: async (milliseconds) => slept.push(milliseconds) },
            });
            const evicted = await client.evictOrphan('job-new');
            pingResponse = { ok: true, busy: true, jobId: 'job-new' };
            const keptCurrent = await client.evictOrphan('job-new');
            pingResponse = { ok: true, busy: false, jobId: null };
            const keptIdle = await client.evictOrphan('job-new');
            const directPing = await client.ping();
            const directCancel = await client.cancel();
            console.log(JSON.stringify({
              evicted, keptCurrent, keptIdle, directPing, directCancel, sent, slept,
            }));
            """
        )
        self.assertTrue(result["evicted"])
        self.assertFalse(result["keptCurrent"])
        self.assertFalse(result["keptIdle"])
        self.assertEqual(result["directPing"], {"ok": True, "busy": False, "jobId": None})
        self.assertEqual(result["directCancel"], {"ok": True})
        self.assertEqual(result["sent"].count("offscreen-cancel"), 2)
        self.assertEqual(result["slept"], [50])

    def test_persisted_result_load_and_clear_are_job_scoped(self) -> None:
        result = self._node_eval(
            """
            const key = 'bookmarkAdvisorOffscreenResult';
            const values = {
              [key]: { jobId: 'job-a', ok: true, result: { reviewed_plan: { actions: [] } } },
            };
            const removed = [];
            const storage = {
              get: async (name) => values[name],
              remove: async (name) => { removed.push(name); delete values[name]; },
            };
            const client = BookmarkAdvisor.Background.OffscreenClient.create({
              chrome: { runtime: { sendMessage: async () => ({ ok: true }) } },
              storage,
            });
            const any = await client.loadPersistedResult();
            const matching = await client.loadPersistedResult('job-a');
            const mismatch = await client.loadPersistedResult('job-b');
            const mismatchCleared = await client.clearPersistedResult('job-b');
            const stillPresent = !!values[key];
            const matchingCleared = await client.clearPersistedResult('job-a');
            console.log(JSON.stringify({
              any, matching, mismatch, mismatchCleared, stillPresent,
              matchingCleared, removed, finalPresent: !!values[key],
            }));
            """
        )
        self.assertEqual(result["any"]["jobId"], "job-a")
        self.assertEqual(result["matching"], result["any"])
        self.assertIsNone(result["mismatch"])
        self.assertFalse(result["mismatchCleared"])
        self.assertTrue(result["stillPresent"])
        self.assertTrue(result["matchingCleared"])
        self.assertEqual(result["removed"], ["bookmarkAdvisorOffscreenResult"])
        self.assertFalse(result["finalPresent"])

    def test_missing_offscreen_support_falls_back_to_ai_facade_with_abort_signal(self) -> None:
        result = self._node_eval(
            """
            const calls = [];
            const aiFacade = {
              generateReviewedPlan: async (options) => {
                calls.push({ mode: 'generate', options });
                return { generated: true };
              },
              reviseReviewedPlan: async (options) => {
                calls.push({ mode: 'revise', options });
                return { revised: true };
              },
            };
            const client = BookmarkAdvisor.Background.OffscreenClient.create({
              chrome: { runtime: { sendMessage: async () => { throw new Error('must not send'); } } },
              storage: { get: async () => null, remove: async () => {} },
              aiFacade,
            });
            const controller = new AbortController();
            const generated = await client.run(
              { id: 'job-generate' }, 'generate', { model: 'm1' }, controller,
            );
            const revised = await client.run(
              { id: 'job-revise' }, 'revise', {
                options: { model: 'm2' }, plan: { actions: [{ action_id: 'a1' }] },
              },
              { controller },
            );
            console.log(JSON.stringify({
              supports: client.supports(), generated, revised,
              calls: calls.map((call) => ({
                mode: call.mode,
                model: call.options.model,
                hasSignal: call.options.signal === controller.signal,
                existingPlan: call.options.existingPlan || null,
              })),
            }));
            """
        )
        self.assertFalse(result["supports"])
        self.assertEqual(result["generated"], {"generated": True})
        self.assertEqual(result["revised"], {"revised": True})
        self.assertEqual(
            result["calls"],
            [
                {"mode": "generate", "model": "m1", "hasSignal": True, "existingPlan": None},
                {
                    "mode": "revise",
                    "model": "m2",
                    "hasSignal": True,
                    "existingPlan": {"actions": [{"action_id": "a1"}]},
                },
            ],
        )


if __name__ == "__main__":
    unittest.main()
